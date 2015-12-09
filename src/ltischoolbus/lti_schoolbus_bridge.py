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
from tornado import httpserver
from tornado import web
import tornado
import tornado.ioloop


USE_CENTRAL_EVENT_LOOP = True

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
    

    def initialize(self, key=None, secret=None, logFile=None, loggingLevel=logging.INFO):
        
        if key is None or secret is None:
            raise ValueError('Both LTI key and LTI secret must be provided to start the server.')
        
        self.key    = key 
        self.secret = secret

        self.logger = None
        
        self.busAdapter = BusAdapter()
        if logFile is None:
            logFile = os.path.join(os.path.dirname(__file__), '../../log/ltischool_log.log')
            
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
                
        self.check_secret(postBodyDict)
            
        target = postBodyDict.get('target', None)
        if target is None:
            self.logErr('POST called without target specification: %s' % str(postBodyDict))
            self.returnHTTPError(400, 'Message did not include a target topic: %s' % str(postBodyDict))
            return
            
        payload = postBodyDict.get('payload', None)
        if payload is None:
            self.logErr('POST called without payload field: %s' % str(postBodyDict))
            self.returnHTTPError(400, 'Message did not include a payload field: %s' % str(postBodyDict))
            return
            
        self.publish_to_bus(target, payload)
        
    def check_secret(self, postBodyDict):
        try:
            key = postBodyDict['key']
            secret = postBodyDict['secret']
        except KeyError:
            self.returnHTTPError(400, 'Either key or secret were not included in LTI request: %s' % str(postBodyDict))
            return
        except TypeError:
            self.returnHTTPError(400, 'POST payload did of LTI request did not form a Python dictionary: %s' % str(postBodyDict))
            return
        
        if key != self.key:
            self.returnHTTPError(400, "Key '%s' is incorrect for this LTI provider." % key)
            return

        if secret != self.secret:
            self.returnHTTPError(400, "Secret '%s' is incorrect for this LTI provider." % secret)
            return

        
    def returnHTTPError(self, status_code, msg):
        self.clear()
        self.set_status(status_code)
        self.finish("<html><body>%s</body></html>" % msg)        

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
        
    
    def setupLogging(self, loggingLevel, logFile=None):
        if self.loggingInitialized:
            # Remove previous file or console handlers,
            # else we get logging output doubled:
            self.logger.handlers = []
            
        # Set up logging:
        self.logger = logging.getLogger('ltibridge')
        if logFile is None:
            handler = logging.StreamHandler()
        else:
            handler = logging.FileHandler(filename=logFile)
        formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        handler.setFormatter(formatter)            
        self.logger.addHandler(handler)
        self.logger.setLevel(loggingLevel)
        self.loggingInitialized = True
 
    def logDebug(self, msg):
        self.logger.debug(msg)

    def logWarn(self, msg):
        self.logger.warn(msg)

    def logInfo(self, msg):
        self.logger.info(msg)

    def logErr(self, msg):
        self.logger.error(msg)
        
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
    parser.add_argument('-k', '--key',
                        action='store',
                        help='LTI key. Default looks in $HOME/.ssh/ltiKey.lti. If not found, will prompt for the key.',
                        default=None)
    parser.add_argument('-s', '--secret',
                        action='store',
                        help='LTI secret. Default looks in $HOME/.ssh/ltiSecret.lti.  If not found, will prompt for the secret.',
                        default=None)
    parser.add_argument('-l', '--logfile', 
                        help='fully qualified log file name to which info and error messages \n' +\
                             'are directed. Default: stdout.',
                        dest='logfile',
                        default=None)

    args = parser.parse_args();
    
    # Key provided? If yes, use it, else
    # look in $HOME/.ssh/ltiKey.lti. If that
    # fails, prompt for key:
    key = args.key 
    if key is None:
        # Try to find pwd in specified user's $HOME/.ssh/ltiKey.lti
        currUserHomeDir = os.getenv('HOME')
        if currUserHomeDir is None:
            key = None
        else:
            try:
                # Look for .ssh/ltiKey.lti:
                with open(os.path.join(currUserHomeDir, '.ssh/ltiKey.lti')) as fd:
                    key = fd.readline().strip()
            except IOError:
                # No .ssh subdir of user's home, or no ltiKey.lti inside .ssh:
                key = None
    if key is None:
        key = getpass.getpass("Enter the LTI auth key: ")

    # Same for the secret:
    secret = args.secret 
    if secret is None:
        # Try to find pwd in specified user's $HOME/.ssh/ltiSecret.lti
        currUserHomeDir = os.getenv('HOME')
        if currUserHomeDir is None:
            secret = None
        else:
            try:
                # Look for .ssh/ltiSecret.lti:
                with open(os.path.join(currUserHomeDir, '.ssh/ltiSecret.lti')) as fd:
                    secret = fd.readline().strip()
            except IOError:
                # No .ssh subdir of user's home, or no ltiSecret.lti inside .ssh:
                secret = None
    if secret is None:
        secret = getpass.getpass("Enter the LTI auth secret: ")


    application = LTISchoolbusBridge.makeApp({'key' : key,
                                              'secret' : secret,
                                              'logFile' : args.logfile,
                                              'loggingLevel' : logging.INFO
                                              }
                                             )

    # We need an SSL capable HTTP server:
    # For configuration without a cert, add "cert_reqs"  : ssl.CERT_NONE
    # to the ssl_options (though I haven't tried it out.):

    http_server = tornado.httpserver.HTTPServer(application,
                                                ssl_options={"certfile": "/home/paepcke/.ssl/MonoCertSha2Expiration2018/mono_stanford_edu_cert.cer",
                                                             "keyfile" : "/home/paepcke/.ssl/MonoCertSha2Expiration2018/mono.stanford.edu.key"
    })
    
    # Set up logging; the logger will be a class variable used
    # by all instances:
    LTISchoolbusBridge.setupLogging(loggingLevel, logFile)
        
    
    
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
            