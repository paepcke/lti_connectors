'''
Created on Apr 29, 2015

@author: paepcke
'''
import argparse
import getpass
import json
import logging
import os
import sys
from ubuntu_sso.utils.txsecrets import SECRET_CONTENT_TYPE

from redis_bus_python.bus_message import BusMessage
from redis_bus_python.redis_bus import BusAdapter

import jsmin
from tornado import httpserver
from tornado import web
import tornado
import tornado.ioloop


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


#*****{"topic" : {"key" : "secret"}
#*****}

class LTISchoolbusBridge(tornado.web.RequestHandler):
    '''
    Operates on two communication systems at once:
    HTTP, and a SchoolBus. Information is received
    on incoming HTTP POST requests that are expected
    to be LTI protocol. Contents of POST requests are
    forwarded by being published to the SchoolBus.
    
    Information flow in the reverse direction is not
    implemented. Once added it should likely follow
    LTI 1.1 conventions (see https://canvas.instructure.com/doc/api/file.assignment_tools.html).
    
    The Web service that handles POST requests from 
    an LTI consumer listens on port LTI_PORT. This 
    constant is a class variable; change to taste.
    
    Expected format from LTI is:
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
    
    If running on mono.stanford.edu, the 
    following URL lets you exercise the service:
    https://lagunita.stanford.edu/courses/DavidU/DC1/David_Course/courseware/918c99bd432c4a83ac14e03cbe774fa0/3cdfb888a5bf480a9f17fc0ca1feb53a/2

    If you run it on your own server, and you have
    a sandbox course on Lagunita, you can create 
    an LTI component as described at 
    http://edx.readthedocs.org/projects/edx-partner-course-staff/en/latest/exercises_tools/lti_component.html
    
    Or: use https://www.hurl.it/ with URL: https://mono.stanford.edu:7075/schoolbus (replace
        7075 with the value of LTI_PORT):
         If you use the GET method there, setting parms to foo=10, you should get an 
         echo that says:
         <html>
            <body>GET method was called: {'foo': ['10']}.</body>
         </html>
         
         If you use the POST method with the same parm, you should get nothing back.
    '''

    LTI_PORT = 7075

    # Remember whether logging has been initialized (class var!):
    loggingInitialized = False
    logger = None
    auth_dict = {}        
    
    def initialize(self):
        
        self.busAdapter = BusAdapter()
            
    # -------------------------------- HTTP Handler ---------

    def get(self):
        '''
        GET requests currently don't do anything. But we
        could use them for info exchange outside of the LTI
        framework.
        '''
        getParms = self.request.arguments
        self.write("<html><body>GET method was called: %s.</body></html>" %str(getParms))


    def post(self):
        '''
        Override the post() method. The
        associated form is available as a 
        dict in self.request.arguments.
        '''
        postBodyForm = self.request.body
        #print(str(postBody))
        #self.write('<!DOCTYPE html><html><body><script>document.getElementById("ltiFrame-i4x-DavidU-DC1-lti-2edb4bca1198435cbaae29e8865b4d54").innerHTML = "Hello iFrame!"</script></body></html>"');    

        #self.echoParmsToEventDispatcher(postBodyForm)
        
        try:
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
        auth fails. 
        
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
        self.clear()
        self.write("Error: %s" % msg)        
        self.set_status(status_code)

        # The following, while simple, tries to put msg into the
        # HTTP header, where newlines are illegal. This limitation
        # often prevents return of a faulty JSON structure: 
        # raise tornado.web.HTTPError(status_code=status_code, reason=msg)

    def echoParmsToEventDispatcher(self, postBodyDict):
        '''
        For testiung only: Write an HTML form back to the calling browser.
        
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
        bus_message = BusMessage(content=payload, topicName=topic,)
        self.busAdapter.publish(bus_message)
    
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
            