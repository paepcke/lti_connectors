#!/usr/bin/env python
# coding: utf-8

'''
Created on Dec 15, 2015

@author: paepcke
'''
import argparse
import json
import os
import socket
import ssl
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
    
    # Tornado application object (empty keyword parms dict):    
    
    application = LtiBridgeDeliveryReceiver.makeApp({})
    
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
            args.certfile = LtiBridgeDeliveryReceiver.guess_cert_path()
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
            args.keyfile = LtiBridgeDeliveryReceiver.guess_key_path()
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
        
    interim_certs_path = os.path.join(os.getenv("HOME"), ".ssl/duo_stanford_edu_interm.cer")
    context = ssl.SSLContext(PROTOCOL_SSLv23)
    context.verify_mode = ssl.CERT_REQUIRED 
    context.load_cert_chain(args.certfile, args.keyfile)
    context.load_verify_locations(interim_certs_path)
    
#     http_server = tornado.httpserver.HTTPServer(application,
#                                                 ssl_options={"certfile": cert_path,
#                                                              "keyfile" : key_path
#     })
    http_server = tornado.httpserver.HTTPServer(application,
                                                ssl_options=context)

    fqdn = socket.getfqdn()
    service_url  = 'https://%s:%s/delivery' % (fqdn, LtiBridgeDeliveryReceiver.LTI_BRIDGE_DELIVERY_TEST_PORT)
    
    print('Starting LTI-Schoolbus bridge test delivery receiver at %s' % service_url)
    
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
            