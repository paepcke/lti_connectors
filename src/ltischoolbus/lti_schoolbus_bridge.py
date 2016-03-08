#!/usr/bin/env python

'''
Created on Apr 29, 2015

TODO:
   o Add SSL to POSTing of delivery. Currently the delivery_rx_server is unhappy w/ ssl-wrong
       Candidates are 'request' package with 'httpsig' package: https://pypi.python.org/pypi/httpsig.
       Latter has (sparse) instructions for use with 'request'. 
       httpsig: what is the 'key_id', and where to put the POST txt;
       they only show GET example. 
   o Maybe test whether automatic redis-server starting works.
   o Document that you must use:
       cd proj-root
       pip install .
     Latter will find the setup.py file.

@author: paepcke
'''
import argparse
from distutils.spawn import find_executable
import functools
import json
import logging
from logging.handlers import TimedRotatingFileHandler
import os
import re
import signal
import socket
import ssl
from subprocess import Popen
import subprocess
import sys
from urllib2 import URLError
import urllib2
import urlparse

from jsmin import jsmin
from jsonfiledict import JsonFileDict
from redis_bus_python.bus_message import BusMessage
from redis_bus_python.redis_bus import BusAdapter
import requests
from requests.exceptions import ConnectionError
from tornado import httpserver
from tornado import web
import tornado
import tornado.ioloop


#from ltischoolbus.jsmin import jsmin
# TODO: # update img with new delivery example (i.e. include ltiKey/ltiSecret)
USE_CENTRAL_EVENT_LOOP = True

# {
#      "ltiKey" : "ltiKey",
#      "ltiSecret" : "ltiSecret",
#      "action" : "publish",
#      "bus_topic" :  "studentAction",
#      "payload" :	    {"event_type": "problem_check",
# 		      "resource_id": "i4x://HumanitiesSciences/NCP-101/problem/__61",
# 		      "student_id": "d4dfbbce6c4e9c8a0e036fb4049c0ba3",
# 		      "answers": {"i4x-HumanitiesSciences-NCP-101-problem-_61_2_1": ["choice_3", "choice_4"]},
# 		      "result": "False",
# 		      "course_id": "HumanitiesSciences/NCP-101/OnGoing"
# 		    }
# }


class LTISchoolbusBridge(tornado.web.RequestHandler):
    '''
    Operates on two communication systems at once:
    HTTP, and a SchoolBus. Information is received
    on incoming HTTP POST requests that are expected
    to be LTI protocol. Contents of POST requests are
    forwarded by being published to the SchoolBus.
    
    Information flow in the reverse direction requires
    the LTI consumer to supply a delivery URL where it
    is ready to receive POSTs. The POST bodys will have
    this format:
            {
                "time"   : "ISO time string",
                "bus_topic"  : "SchoolBus topic of bus message",
                "payload": "message's 'content' field"
            }    
    
    TODO: check against LTI 1.1 conventions 
           (see https://canvas.instructure.com/doc/api/file.assignment_tools.html).    
    
    The Web service that handles POST requests from 
    an LTI consumer listens on port LTI_PORT. This 
    constant is a class variable; change to taste.
    
    Expected format from LTI consumer is:
         {
            "ltiKey"         : <lti-key>,
            "ltiSecret"      : <lti-secret>,
            "action"      : {"publish" | "subscribe" | "unsubscribe"},
            "bus_topic"   : <schoolbus topic>>
            "payload"     :
            {
            "course_id": course_id,
            "resource_id": problem_id,
            "student_id": anonymous_id_for_user(user, None),
            "answers": answers,
            "result": is_correct,
            "event_type": event_type,
            "target_topic" : schoolbus_topic
            }
        }
        
     An example payload for action publish:

        {
            "ltiKey" : "myLtiKey",
            "ltiSecret" : "myLtiSecret",
            "action" : "publish,
            "bus_topic" : "studentAction",
            "payload" :
		    {"event_type": "problem_check",
		      "resource_id": "i4x://HumanitiesSciences/NCP-101/problem/__61",
		      "student_id": "d4dfbbce6c4e9c8a0e036fb4049c0ba3",
		      "answers": {"i4x-HumanitiesSciences-NCP-101-problem-_61_2_1": ["choice_3", "choice_4"]},
		      "result": False,
		      "course_id": "HumanitiesSciences/NCP-101/OnGoing",
            }
        }
        
    Example for subscribe:
        {
            "ltiKey" : "myLtiKey",
            "ltiSecret" : "myLtiSecret",
            "action" : "publish,
            "bus_topic" : "studentAction",
            "payload" : {
		                  "delivery_url" : "https://myMachine.myDomain.edu"
		                }
        }
        
    When a message arrives on the bus, it will be
    POSTed to each subscribed URL, with this body:
    
        {
            "ltiKey" : "myLTIKey",
            "ltiSecret" : "myLTISecret",
            "time" : "2007-01-25T12:00:00Z",
            "payload": "..."
        }
    
    
        
    Authentication is controlled by a config file. See file ltibridge.cnf.example
    of this distribution for the format of this file.
    
    HTTP Error Codes Used:
       400  (Bad Request) if no topic was provided in the request,
                           or if no payload is included,
                           or no delivery URL is included in a subscribe request
       401  (Unauthorized) if ltiKey/ltiSecret are missing or incorrect,
                           or if LTI client is not authorized to subscribe
                           to a particular topic. 
       403  (Forbidden)    if LTI client tries to use HTTP instead of HTTPS
       405  (Method not Allowed) if 'action' field is missing.
                       
       409 (Conflict)      cannot provide both: a POST body, and a GET query
                           in the URL.
       415 (Unsupported Media Type) If message is not legal JSON.
       
       501 (Not Implemented) if 'action' field contains an unknown command.
       
    
    To test, you can use https://www.hurl.it/ with URL: 
       https://yourServer.edu:7075/schoolbus 
    replacing 7075 with the value of LTI_PORT in your installation.
    
    '''

    LTI_BRIDGE_SERVICE_PORT = 7075
    
    # Time to wait for LTI provider (e.g. LMS) to
    # respond when trying to deliver a bus message to it:
    LTI_BRIDGE_DELIVERY_TIMEOUT = 1 # second

    # Remember whether logging has been initialized (class var!):
    loggingInitialized = False
    logger = None
    
    # Path to config file, which holds LTI keys/secrets:
    configfile = None
    # Config file's modification time when auth_dict
    # is initialized from the file:
    auth_file_mod_time = None
    
    # Dict with info obtained from the authentication 
    # config file:
    auth_dict = {}
    
    # Whether or not the redis-server was running when this bridge
    # service was started. If it wasn't running, we start it as
    # part of our startup. The following remembers whether we
    # did start, so we have a choice of killing it upon exit:
    redis_pid = None     
    
    # Keep track of SchoolBus subscriptions:
    
    # File in which jsonfiledict will store subscriptions:
    subscriptions_path = os.path.join(os.path.dirname(__file__), '../../subscriptions/lti_bus_subscriptions.json')

    def initialize(self):
        '''
        This method is call once when the server is started. In 
        contrast, the __init__() method, which we don't override
        in this class is called every time a new request arrives.
        '''
        
        # Create a BusAdapter instance that handles all
        # interactions with the SchoolBus:
        self.busAdapter = BusAdapter()
        
        # Create or read existing JSON file with all
        # subscriptions:
        try:
            self.lti_subscriptions = JsonFileDict(LTISchoolbusBridge.subscriptions_path)
            self.lti_subscriptions.load()
        except (ValueError, IOError):
            # The persistent-subscription file was absent,
            # or contained non-JSON:
            try:
                with open(LTISchoolbusBridge.subscriptions_path, 'r') as fd:
                    subscriptions_raw = fd.readlines()
                if subscriptions_raw is not None and len(subscriptions_raw) > 0:
                    self.logErr('Bad JSON in subscription file %s: %s' % (LTISchoolbusBridge.subscriptions_path,
                                                                          str(subscriptions_raw)))
            except Exception:
                # Can't even read the subscription file:
                self.logErr('Could not read subscription file %s' % LTISchoolbusBridge.subscriptions_path)
            with open(LTISchoolbusBridge.subscriptions_path, 'w') as fd:
                fd.write('{}')
            self.lti_subscriptions = {}
        self.logInfo('Loaded existing subscriptions: %s' %\
                      str(self.lti_subscriptions) if len(self.lti_subscriptions) > 0 else 'No subscriptions on record.')
        
        # Callback for BusAdapter when a message arrives
        # on the bus, destined for an LTI end point:
        self.bus_in_msg_callback = functools.partial(self.bus_to_lti_callback)
        # Bus-inmsg-handler:
        self.bus_in_msg_handler  = functools.partial(self.to_lti_transmitter)
        
        self.published_to_bus_counter = 0
        self.delivered_to_lti_counter = 0
        
        # If there are subscriptions from last time this
        # server ran, then re-subscribe to them:
        for bus_topic in self.lti_subscriptions.keys():
            self.logInfo('Subscribing to bus topic %s' % bus_topic)
            self.busAdapter.subscribeToTopic(bus_topic, self.bus_in_msg_callback)
        
    # -------------------------------- HTTP Handler ---------

    def post(self):
        '''
        Override the post() method. The
        associated form is available as a 
        dict in self.request.arguments.
        
        Logs errors: Bad json in the POST body, missing SchoolBus topic, missing payload. 
        
        '''
        postBodyForm = self.request.body
        #print(str(postBody))
        #self.write('<!DOCTYPE html><html><body><script>document.getElementById("ltiFrame-i4x-DavidU-DC1-lti-2edb4bca1198435cbaae29e8865b4d54").innerHTML = "Hello iFrame!"</script></body></html>"');    

        #self.echoParmsToEventDispatcher(postBodyForm)
        
        try:
            # Turn POST body JSON into a dict:
            postBodyDict = json.loads(str(postBodyForm))
        except ValueError:
            self.logErr('POST called with improper JSON: %s' % str(postBodyForm))            
            self.returnHTTPError(415, 'Message did not include a proper JSON object %s' % str(postBodyForm))
            return

        # Does msg contain the required 'action' field?
        action = postBodyDict.get('action', None)
        if action is None:
            self.logErr("POST called without action field: '%s'" % str(postBodyDict))
            self.returnHTTPError(405, 'Message did not include an action field: %s' % str(postBodyDict))
            return
        # Normalize capitalization:
        action = action.lower()
                
        # Is the required bus_topic field present?                
        target_topic = postBodyDict.get('bus_topic', None)
        if target_topic is None:
            self.logErr('POST called without target_topic specification: %s' % str(postBodyDict))
            self.returnHTTPError(400, 'Message did not include a target_topic field: %s' % str(postBodyDict))
            return

        # Look for LTI key and secret in the dict, and
        # check it against the config file:

        if not self.check_auth(postBodyDict, target_topic):
            # check_auth will return the correct HTTP Error
            # before returning.
            return
            
        payload = postBodyDict.get('payload', None)
        if payload is None:
            self.logErr('POST called without payload field: %s' % str(postBodyDict))
            self.returnHTTPError(400, 'Message did not include a payload field: %s' % str(postBodyDict))
            return

        # Ensure that payload is good JSON;
        if not isinstance(payload, dict):
            try:
                json.loads(payload)
            except ValueError:
                self.logDebug('Bad JSON in payload field of message: %s' % str(payload))
                self.returnHTTPError(415, 'Message payload field does not contain proper JSON: %s' % str(postBodyDict))
                return
        
        # Finally, seems to be a legal msg; process the various actions:
        if action == 'publish':
            self.logDebug("Req to publish to '%s': %s" % (target_topic, str(payload)))
            self.publish_to_bus(target_topic, payload)
            return
        elif action in ['subscribe', 'unsubscribe']:
            # Must have a URL in the payload:
            delivery_url = payload.get('delivery_url', None)
            if delivery_url is None:
                self.logErr("POST called with action '%s', but no delivery URL provided: %s" % (action, str(postBodyDict)))
                self.returnHTTPError(400, "Action '%s' must provide a delivery_url in the payload field; offending message: '%s'" % (action, str(postBodyDict)))
                return
            # Do minimal check of the URL: must be scheme HTTPS to 
            # ensure that message from the bus to the delivery URL are
            # encrypted. Since the delivery will be a POST, there shouldn't
            # be a query or fragment part:
            url_segments = urlparse.urlparse(delivery_url)
            if url_segments.scheme.lower() != 'https':
                self.logErr("POST request specifying non-secure URL '%s': '%s'" % (delivery_url, str(postBodyDict)))
                self.returnHTTPError(403, "Delivery URL must use an encrypted scheme (https); was %s. Offending POST body '%s'" % (delivery_url, str(postBodyDict)))
                return
            if len(url_segments.query) + len(url_segments.fragment) > 0:
                self.logErr("POST request with non-empty query or fragment URL: '%s'" % str(postBodyDict))
                self.returnHTTPError(409, "Delivery URL must not have a query or fragment part, but was '%s'. Offending POST body '%s'" % (delivery_url, str(postBodyDict)))
                return
            # Finally, all seems good for subscribe/unsubsribe:
            if action == 'subscribe':
                self.logInfo('Subscribing to %s; LTI client: %s' % (target_topic, delivery_url))
                self.lti_subscribe(target_topic, delivery_url)
            else:
                self.logInfo('Unsubscribing from %s; LTI client: %s' % (target_topic, delivery_url))
                self.lti_unsubscribe(target_topic, delivery_url)
            return
        else:
            # Unknown action:
            self.logErr("POST called with unknown action value '%s': '%s'" % (action, str(postBodyDict)))
            self.returnHTTPError(501, "Action '%s' is not implemented; offending message: '%s'" % (action, str(postBodyDict)))
            return
            
        return
            
        
    def check_auth(self, postBodyDict, target_topic):
        '''
        Given the payload dictionary and the SchoolBus topic to
        which the information is to be published, check authentication.
        Return True if authentication checks out, else return False.
        If authentication fails for any reason, an appropriate HTTP response
        header will have been sent. The caller should simply abandon
        the request for which authentication was being checked.
        
        The method expectes LTISchoolbusBridge.auth_dict to be initialized.
        If the configuration file that underlies the dict does not have
        an entry for the given topic, auth fails. If the LTI key or LTI secret
        are absent from postBodyDict, auth fails. If either secret or key
        in the payload does not match the key/secret in the config file,
        auth fails. See class comment for config file format.
        
        :param postBodyDict: dictionary parsed from payload JSON
        :type postBodyDict: {string : string}
        :param target_topic: SchoolBus topic for which authentication is to be checked
        :type target_topic: str
        '''
        
        try:
            given_key = postBodyDict['ltiKey']
            given_secret = postBodyDict['ltiSecret']
        except KeyError:
            self.logErr('Either key or secret missing in incoming POST: %s' % str(postBodyDict))
            self.returnHTTPError(401, 'Either key or secret were not included in LTI request: %s' % str(postBodyDict))
            return False
        except TypeError:
            self.logErr('POST body of LTI request did not parse into a Python dictionary: %s' % str(postBodyDict))
            self.returnHTTPError(415, 'POST body of LTI request did not parse into a Python dictionary: %s' % str(postBodyDict))
            return False
        
        try:
            # Get sub-dict with secret and key from config file
            # See class header for config file format:
            auth_entry = LTISchoolbusBridge.auth_dict[target_topic]

            # Compare given key and secret with the key/secret on file
            # for the target bus topic:            
            key_on_record = auth_entry['ltiKey'] 
            if key_on_record != given_key:
                # One more chance: was auth file updated since we
                # last loaded it into auth_dict?
                if self.reload_auth_if_new():
                    # Load the modified auth info again:
                    auth_entry = LTISchoolbusBridge.auth_dict[target_topic]
                    key_on_record = auth_entry['ltiKey'] 
                    # Now is all OK?
                    if key_on_record != given_key:
                        self.logErr("Key '%s' does not match key for topic '%s' in config file." % (given_key, target_topic))
                        # Required response header field for 401-not authenticated:
                        self.set_header('WWW-Authenticate', 'key/secret')
                        self.returnHTTPError(401, "Service not authorized for bus topic '%s'" % target_topic)
                        return False
                else:
                    # Bad ltiKey:
                    self.logErr("Key '%s' does not match key for topic '%s' in config file." % (given_key, target_topic))
                    # Required response header field for 401-not authenticated:
                    self.set_header('WWW-Authenticate', 'key/secret')
                    self.returnHTTPError(401, "Service not authorized for bus topic '%s'" % target_topic)
                    return False
                    
                    
            secret_on_record = auth_entry['ltiSecret'] 
            if secret_on_record != given_secret:
                # One more chance: was auth file updated since we
                # last loaded it into auth_dict?
                if self.reload_auth_if_new():
                    # Load the modified auth info again:
                    auth_entry = LTISchoolbusBridge.auth_dict[target_topic]
                    secret_on_record = auth_entry['ltiSecret'] 
                    # Now is all OK?
                    if secret_on_record != given_secret:
                        self.logErr("Secret '%s' does not match secret for topic '%s' in config file." % (given_secret, target_topic))
                        # Required response header field for 401-not authenticated:
                        self.set_header('WWW-Authenticate', 'key/secret')
                        self.returnHTTPError(401, "Service not authorized for bus topic '%s'" % target_topic)
                        return False
                else:
                    self.logErr("Secret '%s' does not match secret for topic '%s' in config file." % (given_secret, target_topic))
                    # Required response header field for 401-not authenticated:
                    self.set_header('WWW-Authenticate', 'key/secret')
                    self.returnHTTPError(401, "Service not authorized for bus topic '%s'" % target_topic)
                    return False
                    
                
        except KeyError:
            # Either no config file entry for target topic, or malformed
            # config file that does not include both 'ltikey' and 'ltisecret'
            # JSON fields for given target topic: 
            self.logErr("No entry for topic '%s' in config file, or ill-formed config file; --> Requestor not authorized for this topic" %\
                        target_topic)
            # Required response header field for 401-not authenticated:
            self.set_header('WWW-Authenticate', 'given_key/given_secret')
            self.returnHTTPError(401, "Service not authorized for bus topic '%s'" % target_topic)
            return False

        return True

    def reload_auth_if_new(self):
        '''
        Check whether config file with its LTI keys and secrets
        was modified since last load into auth_dict. If so, update
        auth_dict and return True. Else just return False.
        :return True if auth_dict was updated, else return False.
        :rtype bool
        '''
        
        statinfo = os.stat(LTISchoolbusBridge.configfile)
        if LTISchoolbusBridge.auth_file_mod_time < statinfo.st_mtime and\
           LTISchoolbusBridge.load_auth_info(LTISchoolbusBridge.configfile, except_on_failure=False):
            self.logInfo('Noticed that config file %s changed.' % LTISchoolbusBridge.configfile)
            return True
        else:
            return False
        

    def returnHTTPError(self, status_code, msg):
        '''
        Tells tornado that an error occurred in the processing of a
        POST or GET request.
        
        :param status_code: HTTP return code
        :type status_code: int
        :param msg: Arbitrary message that will appear in the browser's window (i.e. not in the header).
                    Therefore may contain newlines or any other chars.
        :type msg: str
        '''
        self.clear()
        # Seems like newlines are bad after all:
        msg = msg.replace('\n', '<newline>')
        self.set_status(status_code, reason=msg)
        

        # The following, while simple, tries to put msg into the
        # HTTP header, where newlines are illegal. This limitation
        # often prevents return of a faulty JSON structure: 
        # raise tornado.web.HTTPError(status_code=status_code, reason=msg)

    def echoParmsToEventDispatcher(self, postBodyDict):
        '''
        For testing only: Write an HTML form back to the calling browser.
        
        :param postBodyDict: Dict that contains the HTML form attr/val pairs.
        :type postBodyDict: {string : string}
        '''
        paramNames = postBodyDict.keys()
        paramNames.sort()
        self.write('<html><body>')
        self.write('<b>LTI-SchoolBus bridge Was Invoked With Parameters:</b><br><br>')
        for key in paramNames:
            self.write('<b>%s: </b>%s<br>' % (key, postBodyDict[key]))
        self.write("</body></html>")
        
    # -------------------------------- SchoolBus Handler ---------
    
    def publish_to_bus(self, topic, payload):
        '''
        Given a topic and an arbitrary string, publishes the
        string to the SchoolBus.
        
        :param topic: topic to which message will be published
        :type topic: str
        :param payload: will be placed in the bus message content field.
        :type payload: str
        '''
        bus_message = BusMessage(content=payload, topicName=topic)
        self.busAdapter.publish(bus_message)
        
        self.published_to_bus_counter += 1
        # Note every 100 messages:
        if self.published_to_bus_counter % 100 == 0:
            self.logInfo('Published total of %s messages to bus.' % self.published_to_bus_counter)
    
    def lti_subscribe(self, topic, url):
        '''
        Allows LTI consumers to subscribe to SchoolBus topics. 
        The consumer must supply a URL to which arriving messages
        and their time stamps are POSTed. It is legal to subscribe
        to the same topic multiple times with different URLs. All 
        URLs will be POSTed to with incoming messages. It is safe
        to subscribe to the same topic with the same URL multiple
        times. This situation is a no-op. It is also legal to have message
        of multiple topics delivered to the same consumer URL.
        
        :param topic: the SchoolBus topic to listen to
        :type topic: str
        :param url: URI where consumer is ready to receive POSTs with incoming messages
        :type url: str
        '''

        try:
            # Do we already have this URL subscribed for this topic?
            self.lti_subscriptions[topic].index(url)
        except KeyError:
            # Nobody is currently subscribed to the topic:
            self.lti_subscriptions[topic] = [url]
            self.lti_subscriptions.save()
        except ValueError:
            # There are subscriptions to the topic, but url is not among them;
            # this is the 'normal' case:
            self.lti_subscriptions[topic].append(url)
            self.lti_subscriptions.save()

        self.busAdapter.subscribeToTopic(topic, functools.partial(self.to_lti_transmitter))
                
    def lti_unsubscribe(self, topic, url):
        '''
        Allows LTI consumers to unsubscribe from a SchoolBus topic.
        It is safe to unsubscribe from a topic/url without first
        subscribing. This event is a no-op. If the given topic
        is subscribed to with multiple delivery URLs, only the
        given URL will no longer receive messages on that topic.
        
        :param topic: topic from which to unsubscribe
        :type topic: str
        :param url: delivery URI associated with the topic 
        :type url: str
        '''
        self.busAdapter.unsubscribeFromTopic(topic)
        try:
            self.lti_subscriptions[topic].remove(url)
            self.lti_subscriptions.save()
        except (KeyError, ValueError):
            # Subscription wasn't in our records:
            pass
        
    def bus_to_lti_callback(self, bus_msg):
        '''
        Called from BusAdapter when a bus message arrives
        for one or more LTI components. We just schedule
        the real handler with the ioloop. This is so that
        the Tornado and BusAdapter threads don't interfere:
        the IOLoop is not thread-safe. self.bus_in_msg_handler
        is the partial function for method to_lti_transmitter()
        
        :param bus_msg: message that arrived on the bus 
        :type bus_msg: BusMessage
        '''
        tornado.ioloop.IOLoop.current().add_callback(self.bus_in_msg_handler, bus_msg)
        
    def to_lti_transmitter(self, bus_msg):
        '''
        Called by BusAdapter with incoming messages to which at least
        one LTI consumer has subscribed. Delivers the message to
        all URLs that were provided in previous calls to lti_subscribe().
        Delivery will be JSON:
            {
                "time"   : "ISO time string",
                "topic"  : "SchoolBus topic of bus message",
                "payload": "message's 'content' field"
            }
        Logged errors: 
             - no subscribers for topic: unsubscribes from the topic as side effect
             - URL is not reachable, so POST failed
             - HTTP-based error returned during POST
        
        :param bus_msg: the incoming SchoolBus message
        :type bus_msg: BusMessage
        '''
        topic = bus_msg.topicName
        try:
            # Get the list of LTI URLs where msgs of this topic are to
            # be delivered:
            subscriber_urls = self.lti_subscriptions[topic]
        except KeyError:
            self.logErr("Server received msg for topic '%s', but subscriber dict has no subscribers for that topic." % topic)
            self.busAdapter.unsubscribeFromTopic(topic)
            return
        
        # Look up the ltiKey and ltiSecret for the
        # topic:
        # Get sub-dict with secret and key from config file
        # See class header for config file format:
        try:
            auth_entry = LTISchoolbusBridge.auth_dict[topic]
            (ltiKey, ltiSecret) = (auth_entry['ltiKey'], auth_entry['ltiSecret'])
        except KeyError:
            # Yes, there is a subscriber for this topic, but
            # not a key and/or secret.
            self.logErr('Received bus msg on topic %s to which subscriptions existed, but no key/secret.' % topic)
            # Unsubscribe from this topic:
            self.busAdapter.unsubscribeFromTopic(topic)
            return
        
        msg_to_post = '{"time" : "%s", "ltiKey" : "%s", "ltiSecret" : "%s", "bus_topic" : "%s", "payload" : "%s"}' %\
            (bus_msg.isoTime, ltiKey, ltiSecret, topic, bus_msg.content)

        # POST the msg to each LTI URL that requested the topic:
        for lti_subscriber_url in subscriber_urls:
            try:
                request = urllib2.Request(lti_subscriber_url, msg_to_post, {'Content-Type': 'application/json'})
                response = urllib2.urlopen(request,             #@UnusedVariable
                                           json.dumps(msg_to_post),
                                           timeout=LTISchoolbusBridge.LTI_BRIDGE_DELIVERY_TIMEOUT) 

#****                #r = requests.post(lti_subscriber_url, data=msg_to_post, verify=False)
#                 r = requests.post(lti_subscriber_url, 
#                                   data=msg_to_post, 
#                                   cert=['/home/paepcke/.ssl/duo_stanford_edu.pem',
#                                         '/home/paepcke/.ssl/duo.stanford.edu.key'],
#                                   verify=True)
            except URLError as e:
                self.logErr('Bad delivery URL %s, SSL configuration for topic %s, or server down (%s).' %\
                             (lti_subscriber_url, topic, `e`))
                continue
#            (status, reason) = (r.status_code, r.reason)
#            if status != 200:
#                self.logErr("Failed to deliver bus message to subscriber %s; %s: %s" % (lti_subscriber_url, status, reason))
            self.delivered_to_lti_counter += 1
            # Note every 100 deliveries:
            if self.delivered_to_lti_counter % 100 == 0:
                self.logInfo('Delivered total of %s messages to LTI clients.' % self.delivered_to_lti_counter)
            
            
    # -------------------------------- Utilities ---------            
        
    @classmethod
    def setupLogging(cls, loggingLevel, logFile=None):
        if cls.loggingInitialized:
            # Remove previous file or console handlers,
            # else we get logging output doubled:
            cls.logger.handlers = []
            
        # Set up logging:
        cls.logger = logging.getLogger('ltibridge')
        if logFile is None:
            handler = logging.StreamHandler()
        else:
            handler = TimedRotatingFileHandler(filename=logFile, 
                                               when='D',          # Units in days
                                               interval=30,       # Rotate every 30 days
                                               backupCount=6)     # Keep at most 6 old logs
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        handler.setFormatter(formatter)            
        cls.logger.addHandler(handler)
        cls.logger.setLevel(loggingLevel)
        cls.loggingInitialized = True
 
    def logDebug(self, msg):
        LTISchoolbusBridge.logger.debug(msg)

    def logWarn(self, msg):
        LTISchoolbusBridge.logger.warn(msg)

    def logInfo(self, msg):
        LTISchoolbusBridge.logger.info(msg)

    def logErr(self, msg):
        LTISchoolbusBridge.logger.error(msg)
        
    @classmethod
    def load_auth_info(cls, configfile, except_on_failure=False):
        '''
        Given location of the configuration file, which holds
        the keys and secrets of authorized LTI components,
        (re)-initialize the class variable auth_dict from
        that file. It is ok to call this method more than once.
        Class variable LTISchoolbusBridge.auth_file_mod_time is
        updated with current file mod time.
        
        :param configfile: full path to config file; by default in $HOME/.ssh/ltibridge.cnf.
        :type configifle: string
        :param except_on_failure: If True exceptions are raised if 
            file not available, or content is ill-formed. If False
            then boolean return value signifies successful load.
        :return True if auth info could be loaded and parsed. Else False.
        :rtype bool
        :raised IOError
        :raised ValueError 
        '''

        try:
            with open(configfile, 'r') as conf_fd:
                # Use jsmin to remove any C/C++ comments from the
                # config file:
                LTISchoolbusBridge.auth_dict = json.loads(jsmin(conf_fd.read()))
                statinfo = os.stat(configfile)
                LTISchoolbusBridge.auth_file_mod_time = statinfo.st_mtime
        except IOError:
            if except_on_failure:
                raise
            else:
                return False
        except ValueError:
            if except_on_failure:
                raise
            else:
                return False

    @classmethod  
    def makeApp(cls, init_parm_dict):
        '''
        Create the tornado application, making it 
        called via http://myServer.stanford.edu:<port>/schoolbus
        
        :param init_parm_dict: keyword args to pass to initialize() method.
        :type init_parm_dict: {string : <any>}
        '''
        
        settings = {
                    'path': os.path.join(os.path.dirname(__file__), 'static_html'),
                    'default_filename': 'index.html'
                    }
        
        # React to HTTPS://<server>:<post>/:  Only GET will work, and will show instructions.
        # and to   HTTPS://<server>:<post>/schoolbus  Only POST will work there.
        handlers = [
                    (r"/schoolbus", LTISchoolbusBridge),
                    (r"/(.*)", tornado.web.StaticFileHandler, settings)
                    ]        
        
        application = tornado.web.Application(handlers)
        return application
    
    @classmethod
    def guess_key_path(cls):
        '''
        Check whether an SSL key file exists, and is readable
        at $HOME/.ssl/<fqdn>.key. If so, the full path is
        returned, else throws IOERROR.

        :raise IOError if default keyfile is not present, or not readable.
        '''
        
        ssl_root = os.getenv('HOME') + '/.ssl'
        fqdn = socket.getfqdn()
        keypath = os.path.join(ssl_root, fqdn + '.key')
        try:
            with open(keypath, 'r'):
                pass
        except IOError:
            raise IOError('No key file %s exists.' % keypath)
        return keypath


    @classmethod
    def guess_cert_path(cls):
        '''
        Check whether an SSL cert file exists, and is readable.
        Will check three possibilities:
        
           - $HOME/.ssl/my_server_edu_cert.cer
           - $HOME/.ssl/my_server_edu.cer
           - $HOME/.ssl/my_server_edu.pem
           
        in that order. 'my_server_edu' is the fully qualified
        domain name of this server.

        If one readable file of that name is found, the full path is
        returned, else throws IOERROR.

        :raise IOError if default keyfile is not present, or not readable.
        '''
        
        ssl_root = os.getenv('HOME') + '/.ssl'
        fqdn = socket.getfqdn().replace('.', '_')
        certpath1 = os.path.join(ssl_root, fqdn + '_cert.cer')
        try:
            with open(certpath1, 'r'):
                return certpath1
        except IOError:
            pass
        try:
            certpath2 = os.path.join(ssl_root, fqdn + '.cer')
            with open(certpath2, 'r'):
                return certpath2
        except IOError:
            pass
        
        certpath3 = os.path.join(ssl_root, fqdn + '.pem')
        try:
            with open(certpath3, 'r'):
                return certpath3
        except IOError:
            raise IOError('None of %s, %s, or %s exists or is readable.' %\
                          (certpath1, certpath2, certpath3))
    
# Note: function not method:
def sig_handler(sig, frame):
    # Schedule call to shutdown, so that all ioloop
    # related calls are from main thread:
    io_loop = tornado.ioloop.IOLoop.instance()
    # Schedule the shutdown for after all pending
    # requests have been serviced:
    print('Shutting down LTI-to-SchoolBus bridge...')
    io_loop.add_callback(io_loop.stop)


def is_running(process):
    '''
    Return true if Linux process with given name is
    running.
    
    :param process: process name as appears in ps -axw
    :type process: string
    '''
    search_proc = subprocess.Popen(['ps', 'axw'],stdout=subprocess.PIPE)
    for ps_line in search_proc.stdout:
        if re.search(process, ps_line):
            return True 
    return False
    

if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog=os.path.basename(sys.argv[0]), formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument('-c', '--configfile',
                        action='store',
                        help='Full configuration file path. If absent, looks for $HOME/.ssh/ltibridge.cnf',
                        default=None)
    parser.add_argument('-f', '--logfile', 
                        help='Fully qualified log file name to which info and error messages \n' +\
                             'are directed. Default: stdout.',
                        dest='logfile',
                        default=os.path.join(os.path.dirname(__file__), '../../log/ltischool_log.log'))
    parser.add_argument('-l', '--loglevel', 
                        choices=['critical', 'error', 'warning', 'info', 'debug'],
                        help='Logging level: one of critical, error, warning, info, debug.',
                        dest='loglevel',
                        default=None)
    parser.add_argument('--sslcert',
                        help='Absolute path to SSL certificate file.',
                        dest='certfile',
                        default=None
                        )
    parser.add_argument('--sslkey',
                        help='Absolute path to SSL key file.',
                        dest='keyfile',
                        default=None
                        )

    args = parser.parse_args();
    

    if args.loglevel == 'critical':
        loglevel = logging.CRITICAL
    elif args.loglevel == 'error':
        loglevel = logging.ERROR
    elif args.loglevel == 'warning':
        loglevel = logging.WARNING
    elif args.loglevel == 'info':
        loglevel = logging.INFO
    elif args.loglevel == 'debug':
        loglevel = logging.DEBUG
    else:
        loglevel = logging.NOTSET
     
    # Catch SIGTERM (cnt-C):
    signal.signal(signal.SIGTERM, sig_handler)
       
    # If the redis-server is not running, complain:
    if (not is_running('redis-server')):
        executable = find_executable('redis-server')
        if executable is None:
            print("The necessary program 'redis-server' is not running, and we could not find its executable.")
            sys.exit()
        print("Required redis-server not running; starting it now.")
        print("To run the service manually ahead of time: cd %s;redis-server &" % os.path.dirname(executable))
        # Remember that we started the server, and kill at upon clean exit:
        LTISchoolbusBridge.redis_pid = Popen([executable]).pid
    else:
        LTISchoolbusBridge.redis_pid = None
        
    # Set up logging; the logger will be a class variable used
    # by all instances:
    # Ensure that the log file directory exists
    try:
        # Try to make intermediate dirs if needed.
        # This statement will throw an exception
        # if args.logile is none, or creation is
        # impossible, or the director(ies) already
        # exist. Just give it a try:
        os.makedirs(os.path.dirname(args.logfile))
    except:
        pass
    LTISchoolbusBridge.setupLogging(loggingLevel=loglevel, logFile=args.logfile)
    
    # Read the config file, and make it available as a dict:
    configfile = args.configfile
    if configfile is None:
        configfile = os.path.join(os.getenv('HOME'), '.ssh/ltibridge.cnf')
        if not os.path.isfile(configfile):
            with open(configfile, 'a+') as fd:
                fd.write('{}')
    LTISchoolbusBridge.configfile = configfile
    try:
        LTISchoolbusBridge.load_auth_info(configfile, except_on_failure=True)
    except IOError:
        print('No configuration file found at %s' % configfile)
        sys.exit()
    except ValueError as e:
        print("Bad confiuration file syntax: %s" % `e`)
        sys.exit()
    
    # Tornado application object (empty keyword parms dict):    
    
    application = LTISchoolbusBridge.makeApp({})
    
    # If no SSL cert/key file was provided in a CLI option,
    # make an educated guess: 
    #   For cert file try:
    #      $HOME/.ssl/my_server_edu_cert.cer
    #      $HOME/.ssl/my_server_edu.cer
    #
    #   For key file try:
    #      $HOME/.ssl/my.server.edu.key
    #
    try:
        if args.certfile is None:
            # Will throw IOError exception if not found:
            args.certfile = LTISchoolbusBridge.guess_cert_path()
        else:
            # Was given cert path in CLI option. Check that
            # it's there and readable:
            try:
                with open(args.certfile, 'r'):
                    pass
            except IOError as e:
                raise IOError('Cert file %s does not exist or is not readable.' % args.certfile)
    except IOError as e:
        print('Cannot start server; no SSL certificate: %s.' % `e`)
        sys.exit()
    
    try:
        if args.keyfile is None:
            # Will throw IOError exception if not found:
            args.keyfile = LTISchoolbusBridge.guess_key_path()
        else:
            # Was given cert path in CLI option. Check that
            # it's there and readable:
            try:
                with open(args.keyfile, 'r'):
                    pass
            except IOError:
                raise IOError('Key file %s does not exist or is not readable.' % args.keyfile)
    except IOError as e:
        print('Cannot start server; no SSL key: %s.' % `e`)
        sys.exit()
    
    # We need an SSL capable HTTP server:
    # For configuration without a cert, add "cert_reqs"  : ssl.CERT_NONE
    # to the ssl_options (though I haven't tried it out.):

    http_server = tornado.httpserver.HTTPServer(application,
                                                ssl_options={"certfile": args.certfile,
                                                             "keyfile" : args.keyfile
    })

    fqdn = socket.getfqdn()
    service_url  = 'https://%s:%s/schoolbus' % (fqdn, LTISchoolbusBridge.LTI_BRIDGE_SERVICE_PORT)
    info_url     = 'https://%s:%s/' % (fqdn, LTISchoolbusBridge.LTI_BRIDGE_SERVICE_PORT)
    print('Starting LTI-Schoolbus bridge for POST service at %s (info service at %s)' % (service_url, info_url))
    
    # Run the app on its port:
    # Instead of application.listen, as in non-SSL
    # services, the http_server is told to listen:
    #*****application.listen(LTISchoolbusBridge.LTI_PORT)
    http_server.listen(LTISchoolbusBridge.LTI_BRIDGE_SERVICE_PORT)
    try:
        tornado.ioloop.IOLoop.instance().start()
    except KeyboardInterrupt:
            print('LTI-to-Schoolbus bridge has stopped.')
            sys.exit()
            