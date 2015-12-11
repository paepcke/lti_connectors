'''
Created on Apr 29, 2015

@author: paepcke
'''
import argparse
import functools
import getpass
import json
import logging
import os
import sys
from ubuntu_sso.utils.txsecrets import SECRET_CONTENT_TYPE

import jsmin
import requests
from redis_bus_python.bus_message import BusMessage
from redis_bus_python.redis_bus import BusAdapter
from tornado import httpserver
from tornado import web
import tornado
import tornado.ioloop
from requests.exceptions import ConnectionError

# TODO: - Switch subscribe/unsubscribe from GET to POST so that key/secret can be included
#       - Initialize the subscription jsonfiledict in __main__.
#       - More in-method comments

USE_CENTRAL_EVENT_LOOP = True

# {
#      "key" : "ltiKey",
#      "secret" : "ltiSecret",
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
                "topic"  : "SchoolBus topic of bus message",
                "payload": "message's 'content' field"
            }    
    
    TODO: check against LTI 1.1 conventions 
           (see https://canvas.instructure.com/doc/api/file.assignment_tools.html).    
    
    The Web service that handles POST requests from 
    an LTI consumer listens on port LTI_PORT. This 
    constant is a class variable; change to taste.
    
    Expected format from LTI consumer is:
         {
            'key'         : <lti-key>,
            'secret'      : <lti-secret>
            'bus_topic'   : <schoolbus topic>
            'payload'     :
            {
            'course_id': course_id,
            'resource_id': problem_id,
            'student_id': anonymous_id_for_user(user, None),
            'answers': answers,
            'result': is_correct,
            'event_type': event_type,
            'target_topic' : schoolbus_topic
            }
        }
        
     An example payload before it gets urlencoded:

        {
            'key' : 'myLtiKey',
            'secret' : 'myLtiSecret',
            'bus_topic' : 'studentAction',
            'payload' :
		    {'event_type': 'problem_check',
		      'resource_id': 'i4x://HumanitiesSciences/NCP-101/problem/__61',
		      'student_id': 'd4dfbbce6c4e9c8a0e036fb4049c0ba3',
		      'answers': {'i4x-HumanitiesSciences-NCP-101-problem-_61_2_1': ['choice_3', 'choice_4']},
		      'result': False,
		      'course_id': 'HumanitiesSciences/NCP-101/OnGoing',
            }
        }
        
    Authentication is controlled by a config file. See file ltibridge.cnf.example
    of this distribution for the format of this file.
    
    To test, you can use https://www.hurl.it/ with URL: 
       https://yourServer.edu:7075/schoolbus 
    replacing 7075 with the value of LTI_PORT in your installation.
    
    '''

    LTI_PORT = 7075

    # Remember whether logging has been initialized (class var!):
    loggingInitialized = False
    logger = None
    auth_dict = {}        
    
    def initialize(self):
        
        # Create a BusAdapter instance that handles all
        # interactions with the SchoolBus:
        self.busAdapter = BusAdapter()
            
    # -------------------------------- HTTP Handler ---------

    def get(self):
        '''
        GET is used for the following:
            - Subscribe to SchoolBus topic: http://.../?action=subscribe&topic=myTopic&url=myDeliveryUrl
            - Unsubscribe from a SchoolBus topic: http://.../?action=unsubscribe&topic=myTopic&url=myDeliveryUrl
        '''
        
        getParms = self.request.arguments
        #self.write("<html><body>GET method was called: %s.</body></html>" %str(getParms))
        try:
            action = getParms['action']
            topic  = getParms['topic']
            url    = getParms['url']
        except KeyError:
            self.logErr('Bad GET request; missing query key/val: %s' % str(getParms))
            self.returnHTTPError(400, "GET requests must include key/value pairs 'action, 'topic', and 'url'")
            return
        if action == 'subscribe':
            self.lti_subscribe(topic, url)
        elif action == 'unsubscribe':
            self.lti_unsubscribe(topic, url)
        else:
            self.logErr('Bad GET request; non-implemented action: %s' % action)
            self.returnHTTPError(501, "Only methods 'subscribe' and 'unsubscribe' are implemented; '%s' is not." % action)
            return

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
            self.returnHTTPError(400, 'Message did not include a proper JSON object %s' % str(postBodyForm))
            return
                
        target_topic = postBodyDict.get('bus_topic', None)
        if target_topic is None:
            self.logErr('POST called without target_topic specification: %s' % str(postBodyDict))
            self.returnHTTPError(400, 'Message did not include a target_topic topic: %s' % str(postBodyDict))
            return

        # Look for LTI key and secret in the dict, and
        # check it against the config file:

        if not self.check_auth(postBodyDict, target_topic):
            return
            
            
        payload = postBodyDict.get('payload', None)
        if payload is None:
            self.logErr('POST called without payload field: %s' % str(postBodyDict))
            self.returnHTTPError(400, 'Message did not include a payload field: %s' % str(postBodyDict))
            return
            
        self.publish_to_bus(target_topic, payload)
        
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
            given_key = postBodyDict['key']
            given_secret = postBodyDict['secret']
        except KeyError:
            self.logErr('Either key or secret missing in incoming POST: %s' % str(postBodyDict))
            self.returnHTTPError(400, 'Either key or secret were not included in LTI request: %s' % str(postBodyDict))
            return False
        except TypeError:
            self.logErr('POST JSON payload of LTI request did not parse into a Python dictionary: %s' % str(postBodyDict))
            self.returnHTTPError(400, 'POST JSON payload of LTI request did not parse into a Python dictionary: %s' % str(postBodyDict))
            return False
        
        try:
            # Get sub-dict with secret and key from config file
            # See class header for config file format:
            auth_entry = LTISchoolbusBridge.auth_dict[target_topic]

            # Compare given key and secret with the key/secret on file
            # for the target bus topic:            
            key_on_record = auth_entry['ltiKey'] 
            if key_on_record != given_key:
                self.logErr("Key '%s' does not match key for topic '%s' in config file." % (given_key, target_topic))
                # Required response header field for 401-not authenticated:
                self.set_header('WWW-Authenticate', 'key/secret')
                self.returnHTTPError(401, "Service not authorized for bus topic '%s'" % target_topic)
                return False

            secret_on_record = auth_entry['ltiSecret'] 
            if secret_on_record != given_secret:
                self.logErr("Secret '%s' does not match secret for topic '%s' in config file." % (given_secret, target_topic))
                # Required response header field for 401-not authenticated:
                self.set_header('WWW-Authenticate', 'key/secret')
                self.returnHTTPError(401, "Service not authorized for bus topic '%s'" % target_topic)
                return False
                
        except KeyError:
            # Either no config file entry for target topic, or malformed
            # config file that does not include both 'ltikey' and 'ltisecret'
            # JSON fields for given target topic: 
            self.logErr("Topic '%s' does not have an entry in the config file, or ill-formed config file for that topic." % target_topic)
            # Required response header field for 401-not authenticated:
            self.set_header('WWW-Authenticate', 'given_key/given_secret')
            self.returnHTTPError(401, "Service not authorized for bus topic '%s'" % target_topic)
            return False

        return True

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
        self.write("Error: %s" % msg)        
        self.set_status(status_code)

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
        bus_message = BusMessage(content=payload, topicName=topic,)
        self.busAdapter.publish(bus_message)
    
    def lti_subscribe(self, topic, url):
        '''
        Allows LTI consumers to subscribe to SchoolBus topics. 
        The consumer must supply a URL to which arriving messages
        and their time stamps are POSTed. It is legal to subscribe
        to the same topic multiple times with the same URL. All 
        URLs will be POSTed to with incoming messages. It is safe
        to subscribe to the same topic with the same URL multiple
        times. This event is a no-op. It is also legal to have message
        of multiple topics delivered to the same consumer URL.
        
        :param topic: the SchoolBus topic to listen to
        :type topic: str
        :param url: URI where consumer is ready to receive POSTs with incoming messages
        :type url: str
        '''
        self.busAdapter.subscribeToTopic(topic, functools.partial(self.to_lti_transmitter))
        try:
            # Do we already have this URL subscribed for this topic?
            LTISchoolbusBridge.lti_subscriptions[topic].index(url)
        except KeyError:
            # Nobody is currently subscribed to the topic:
            LTISchoolbusBridge.lti_subscriptions[topic] = [url]
            LTISchoolbusBridge.lti_subscriptions.save()
            return
        except ValueError:
            # There are subscriptions to the topic, but url is not among them;
            # this is the 'normal' case:
            LTISchoolbusBridge.lti_subscriptions[topic].append(url)
            LTISchoolbusBridge.lti_subscriptions.save()
            return
        
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
            LTISchoolbusBridge.lti_subscriptions[topic].remove(url)
            LTISchoolbusBridge.lti_subscriptions.save()
        except (KeyError, ValueError):
            # Subscription wasn't in our records:
            pass
        
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
        topic = bus_msg.topicName()
        try:
            subscriber_urls = LTISchoolbusBridge.subsciber_dict[topic]
        except KeyError:
            self.logErr("Server received msg for topic '%s', but subscriber dict has no subscribers for that topic." % topic)
            self.busAdapter.unsubscribeFromTopic(topic)
            return
        msg_to_post = '{"time" : "%s", "topic" : "%s", "payload" : "%s"}' % (bus_msg.isoTime(), topic, bus_msg.content)
        for lti_subscriber_url in subscriber_urls:
            try:
                r = requests.post(lti_subscriber_url, msg_to_post)
            except ConnectionError:
                self.logErr('Bad delivery URL %s for topic %s' % (lti_subscriber_url, topic))
                continue
            (status, reason) = (r.status_code, r.reason)
            if status != '200':
                self.logErr("Failed to deliver bus message to subscriber %s; %s: %s" % (lti_subscriber_url, status, reason))
            
            
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
            handler = logging.FileHandler(filename=logFile)
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
    def makeApp(self, init_parm_dict):
        '''
        Create the tornado application, making it 
        called via http://myServer.stanford.edu:<port>/schoolbus
        
        :param init_parm_dict: keyword args to pass to initialize() method.
        :type init_parm_dict: {string : <any>}
        '''
        application = tornado.web.Application([
            (r"/schoolbus", LTISchoolbusBridge, init_parm_dict),
            ])
        return application

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
        
    # Set up logging; the logger will be a class variable used
    # by all instances:
    LTISchoolbusBridge.setupLogging(loggingLevel=loglevel, logFile=args.logfile)
    
    # Read the config file, and make it available as a dict:
    configfile = args.configfile
    if configfile is None:
        configfile = os.path.join(os.getenv('HOME'), '.ssh/ltibridge.cnf')
    
    try:
        with open(configfile, 'r') as conf_fd:
            # Use jsmin to remove any C/C++ comments from the
            # config file:
            LTISchoolbusBridge.auth_dict = json.loads(jsmin.jsmin(conf_fd.read()))
    except IOError:
        print('No configuration file found at %s' % configfile)
        sys.exit()
    except ValueError as e:
        print("Bad confiuration file syntax: %s" % `e`)
        sys.exit()
    
    # Tornado application object (empty keyword parms dict):    
    
    application = LTISchoolbusBridge.makeApp({})
    
    # We need an SSL capable HTTP server:
    # For configuration without a cert, add "cert_reqs"  : ssl.CERT_NONE
    # to the ssl_options (though I haven't tried it out.):

    http_server = tornado.httpserver.HTTPServer(application,
                                                ssl_options={"certfile": "/home/paepcke/.ssl/MonoCertSha2Expiration2018/mono_stanford_edu_cert.cer",
                                                             "keyfile" : "/home/paepcke/.ssl/MonoCertSha2Expiration2018/mono.stanford.edu.key"
    })
    
    print('Starting LTI-Schoolbus bridge on port %s' % LTISchoolbusBridge.LTI_PORT)
    
    # Run the app on its port:
    # Instead of application.listen, as in non-SSL
    # services, the http_server is told to listen:
    #*****application.listen(LTISchoolbusBridge.LTI_PORT)
    http_server.listen(LTISchoolbusBridge.LTI_PORT)
    try:
        tornado.ioloop.IOLoop.instance().start()
    except KeyboardInterrupt:
            print('Stopping LTI-Schoolbus bridge.')
            sys.exit()
            