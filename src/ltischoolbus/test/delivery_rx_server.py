#!/usr/bin/env python
# coding: utf-8

'''
Example for an endpoint in an LTI module, such as an LMS.
The example interacts with the lti_schoolbus_bridge server
to subscribe to a topic, receive a message of that topic
from the bus, and unsubscribes. All these interactions
occur via HTTP POST requests.  

Created on Dec 15, 2015

@author: paepcke
'''
import argparse
import json
import os
import socket
import ssl
import sys
import urllib2

from tornado import httpserver
from tornado import ioloop
from tornado import web
import tornado
from tornado.gen import coroutine


class LtiBridgeDeliveryReceiver(tornado.web.RequestHandler):
    '''
    Expects POST messages with content:

    {"time"   : "ISO time string",
     "topic"  : "Msg's SchoolBus topic",
     "payload": "Msg's 'content' field"
    }
    
    on port MY_DELIVERY_PORT

    '''
    
    MY_DELIVERY_PORT = 7076
    LTI_BRIDGE_SERVICE_PORT = 7075
    LTI_BRIDGE_URL = 'https://%s:%s/schoolbus' % (socket.getfqdn(), LTI_BRIDGE_SERVICE_PORT)
    MY_DELIVERY_URL = 'https://%s:%s/delivery' % (socket.getfqdn(), MY_DELIVERY_PORT)
    CONTENT_LOCK_FILE_PATH_ROOT = os.path.join(os.path.dirname(__file__), 'delivery_content.txt')
    DELIVERY_TEST_TOPIC = 'deliveryTest'    
    TEST_SUBSCRIBE_DICT = {"ltiKey" : "ltiKey",\
                           "ltiSecret" : "ltiSecret",\
                           "action" : "subscribe",\
                           "bus_topic" : DELIVERY_TEST_TOPIC,\
                           "payload" : {\
                		                 "delivery_url" : MY_DELIVERY_URL\
                		               },\
                           }    
    TEST_UNSUBSCRIBE_DICT = {"ltiKey" : "ltiKey",\
                           "ltiSecret" : "ltiSecret",\
                           "action" : "unsubscribe",\
                           "bus_topic" : DELIVERY_TEST_TOPIC,\
                           "payload" : {\
                		                 "delivery_url" : MY_DELIVERY_URL\
                		               },\
                           }    
    
    
    def get(self):
        '''
        The HTTP GET msg will just return information about this server.
        '''
        self.write("This is a delivery test server for the LTI-to-Schoolbus bridge.")
        self.write("The business side is POST to HTTPS://<server>:%s/delivery" % LtiBridgeDeliveryReceiver.LTI_BRIDGE_SERVICE_PORT)
    
    def post(self):
        '''
        Received a message from the lti_schoolbus_bridge. This msg
        originated from the SchoolBus, where it was published by some
        remote entity.
        '''
        
        postBodyForm = self.request.body
        try:
            # Turn POST body JSON into a dict:
            postBodyDict = json.loads(str(postBodyForm))
        except ValueError:
            print('POST called with improper JSON: %s' % str(postBodyForm))            
            return

        #print(str(postBodyDict))
        MsgManager.get_instance().handle_delivered_msg(str(postBodyDict))
          
class MsgManager(object):
    '''
    Subscribes/unsubscribes from topics via POST msgs to the LTI bridge.
    Also holds the handle_delivered_msg() that is invoked when a msg
    arrives from the bus via the lti_schoolbus_bridge.

    This class could be folded into the LtiBridgeDeliveryReceiver. But 
    I find this organization cleaner.
    '''
    
    instance = None
    # File prefix P for files P.lock and P.txt. P.lock will be
    # used by delivery_rx_server.py to prevent a unittest 
    # from reading the P.txt file before it is fully written.
    # The delivery_rx_server writes any received messages
    # into P.txt, removing P.lock after write is complete.
    # P is CONTENT_LOCK_FILE_PATH_ROOT:
    CONTENT_LOCK_FILE_PATH_ROOT = os.path.join(os.path.dirname(__file__), 'delivery_content_file')
       
       
    @classmethod
    def get_instance(cls):
        '''
        Singleton pattern.
        '''
        if MsgManager.instance is not None:
            return MsgManager.instance
        else:
            MsgManager.instance = MsgManager()
            return MsgManager.instance

    def handle_delivered_msg(self, json_str):
        '''
        A message has arrived from the bus via the lti_schoolbus_bridge.
        You can do anything you want here. But note that the 
        bridge HTTP POST request is open until this method finishes.
        That's because this method is called from the POST reception method.
        To decouple the delivery HTTP connection from this handler,
        make them both coroutines, or make this class a thread.
        
        In this example handler, which is used by the unittests, 
        we write the arrived message into a file that the unittests
        know about, and will then remove an associated lock file that
        tells the unittest that a result was written.
        
        :param json_str: message content
        :type json_str: string
        '''
        
        # Assume msg originator has placed a lock file into the current dir.
        # Write the received msg to an agree-upon .txt file:
        with open(MsgManager.CONTENT_LOCK_FILE_PATH_ROOT + '.txt', 'w') as fd:
            fd.write(json_str)
        # Remove the lock file for unittests to know they can read the .txt file now:
        os.remove(MsgManager.CONTENT_LOCK_FILE_PATH_ROOT + '.lock')
                    
    def subscribe_to_topic(self, topic):
        '''
        Subscribe to the topic that the unittests will
        post to. But first ensure that no old deliver_content.txt
        file is lying around. It will be created and
        filled with some content when a message is received
        into post().
        
        :param topic: topic to subscribe to
        :type topic: string
        '''
        self.send_to_lti_bridge(LtiBridgeDeliveryReceiver.TEST_SUBSCRIBE_DICT)

    def unsubscribe_from_topic(self, topic):
        '''
        Unsubscribe from the topic that the unittests will
        post to.
        
        :param topic: topic to subscribe to
        :type topic: string
        '''
        self.send_to_lti_bridge(LtiBridgeDeliveryReceiver.TEST_UNSUBSCRIBE_DICT)
        
    
    def send_to_lti_bridge(self, data_dict):
        
        request = urllib2.Request(LtiBridgeDeliveryReceiver.LTI_BRIDGE_URL, 
                                  data_dict, 
                                  {'Content-Type': 'application/json'})
        response = urllib2.urlopen(request, json.dumps(data_dict)) #@UnusedVariable
        return True
    

    def makeApp(self, init_parm_dict):
        '''
        Create the tornado application, making it 
        called via http://myServer.stanford.edu:<port>/schoolbus
        
        :param init_parm_dict: keyword args to pass to initialize() method.
        :type init_parm_dict: {string : <any>}
        '''
        
        # React to HTTPS://<server>:<post>/:  Only GET will work, and will show instructions.
        # and to   HTTPS://<server>:<post>/schoolbus  Only POST will work there.
        handlers = [
                    (r"/delivery", LtiBridgeDeliveryReceiver),
                    ]        
        
        application = tornado.web.Application(handlers)
        return application

    def guess_key_path(self):
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


    def guess_cert_path(self):
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
    

if __name__ == '__main__':

    parser = argparse.ArgumentParser(prog=os.path.basename(sys.argv[0]), formatter_class=argparse.RawTextHelpFormatter)
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
    
    msg_manager = MsgManager.get_instance()
    
    # Tornado application object (empty keyword parms dict):    
    
    application = msg_manager.makeApp({})
    
    # We need an SSL capable HTTP server:
    # For configuration without a cert, add "cert_reqs"  : ssl.CERT_NONE
    # to the ssl_options (though I haven't tried it out.).
    # We assume that certificate and key are in the 
    # following places:
    #     $HOME/.ssl/<fqdn>_cert.cer
    #     $HOME/.ssl/<fqdn>.cer
    #     $HOME/.ssl/<fqdn>.pem
    # and:
    #     $HOME/.ssl/<fqdn>.key
    # If yours are different, use the --sslcert and --sslkey
    # CLI options.

    try:
        if args.certfile is None:
            # Will throw IOError exception if not found:
            args.certfile = msg_manager.guess_cert_path()
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
            args.keyfile = msg_manager.guess_key_path()
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

    # Hack: I can't get Eclipse to find ssl.PROTOCOL_SSLv23, though
    #       CLI python does. So we set it here. Yikes:
    try:
        from ssl import PROTOCOL_SSLv23
    except ImportError:
        PROTOCOL_SSLv23 = 2
        
    fqdn = socket.getfqdn()

# The following context-way of setting ssl configurations only
# works starting in Python 2.7.9
#     interim_certs_path = os.path.join(os.getenv("HOME"), ".ssl/duo_stanford_edu_interm.cer")
#     context = ssl.SSLContext(PROTOCOL_SSLv23)
#     context.verify_mode = ssl.CERT_REQUIRED 
#     context.load_cert_chain(args.certfile, args.keyfile)
#     context.load_verify_locations(interim_certs_path)

#     http_server = tornado.httpserver.HTTPServer(application,
#                                                 ssl_options=context)
    
    http_server = tornado.httpserver.HTTPServer(application,
                                                ssl_options={"certfile": args.certfile,
                                                             "keyfile" : args.keyfile
    })

    service_url  = 'https://%s:%s/delivery' % (fqdn, LtiBridgeDeliveryReceiver.MY_DELIVERY_PORT)
    
    print('Starting LTI-Schoolbus bridge test delivery receiver at %s' % service_url)
    
    # Run the app on its port:
    # Instead of application.listen, as in non-SSL
    # services, the http_server is told to listen:
    #*****application.listen(LTISchoolbusBridge.MY_DELIVERY_TEST_PORT)
    http_server.listen(LtiBridgeDeliveryReceiver.MY_DELIVERY_PORT)
    
    # Subscribe to the test topic:
    msg_manager.subscribe_to_topic(LtiBridgeDeliveryReceiver.DELIVERY_TEST_TOPIC)
    try:
        tornado.ioloop.IOLoop.instance().start()
    except KeyboardInterrupt:
            print('Stopping LTI-Schoolbus bridge test delivery receiver.')
    finally:
        print('Unsubscribing from %s' % LtiBridgeDeliveryReceiver.DELIVERY_TEST_TOPIC)
        msg_manager.unsubscribe_from_topic(LtiBridgeDeliveryReceiver.DELIVERY_TEST_TOPIC)
        print('LTI-Schoolbus bridge test delivery receiver stopped.')
