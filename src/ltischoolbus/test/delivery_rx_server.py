#!/usr/bin/env python
# coding: utf-8

'''
Created on Dec 15, 2015

@author: paepcke
'''
import json
import os
import socket
import sys

from tornado import httpserver
from tornado import ioloop
from tornado import web
import tornado


class LtiBridgeDeliveryReceiver(tornado.web.RequestHandler):
    '''
    Expects POST messages with content:

    {"time"   : "ISO time string",
     "topic"  : "Msg's SchoolBus topic",
     "payload": "Msg's 'content' field"
    }
    
    on port LTI_BRIDGE_DELIVERY_TEST_PORT

    '''
    
    LTI_BRIDGE_DELIVERY_TEST_PORT = 7076
    
    def get(self):
        self.write("This is a delivery test server for the LTI-to-Schoolbus bridge.")
        self.write("The business side is POST to HTTPS://<server>:%s/delivery" % LtiBridgeDeliveryReceiver.LTI_BRIDGE_DELIVERY_TEST_PORT)
    
    def post(self):
        postBodyForm = self.request.body
        try:
            # Turn POST body JSON into a dict:
            postBodyDict = json.loads(str(postBodyForm))
        except ValueError:
            print('POST called with improper JSON: %s' % str(postBodyForm))            
            return

        print(str(postBodyDict))

    @classmethod  
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
    

if __name__ == '__main__':
    
    # Tornado application object (empty keyword parms dict):    
    
    application = LtiBridgeDeliveryReceiver.makeApp({})
    
    # We need an SSL capable HTTP server:
    # For configuration without a cert, add "cert_reqs"  : ssl.CERT_NONE
    # to the ssl_options (though I haven't tried it out.).
    # We assume that certificate and key are in the 
    # following places:
    #     $HOME/.ssl/<fqdn>_cert.cer
    #     $HOME/.ssl/<fqdn>.key
    # If yours are different, change the statements below

    # Get fully-qualified domain name of this server:
    server_name = socket.getfqdn()
    cert_path = os.path.join(os.getenv("HOME"), ".ssl/%s.cer" % server_name)
    key_path  = os.path.join(os.getenv("HOME"), ".ssl/%s.key" % server_name)
                             
    http_server = tornado.httpserver.HTTPServer(application,
                                                ssl_options={"certfile": cert_path,
                                                             "keyfile" : key_path
    })
    
    print('Starting LTI-Schoolbus bridge test delivery receiver on port %s' % LtiBridgeDeliveryReceiver.LTI_BRIDGE_DELIVERY_TEST_PORT)
    
    # Run the app on its port:
    # Instead of application.listen, as in non-SSL
    # services, the http_server is told to listen:
    #*****application.listen(LTISchoolbusBridge.LTI_BRIDGE_DELIVERY_TEST_PORT)
    http_server.listen(LtiBridgeDeliveryReceiver.LTI_BRIDGE_DELIVERY_TEST_PORT)
    try:
        tornado.ioloop.IOLoop.instance().start()
    except KeyboardInterrupt:
            print('Stopping LTI-Schoolbus bridge test delivery receiver.')
            sys.exit()
            