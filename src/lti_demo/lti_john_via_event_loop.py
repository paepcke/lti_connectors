'''
Created on Apr 30, 2015

@author: paepcke
'''

import tornado.ioloop
import tornado.web
from tornado import httpclient 


class LTIJohnProvider(tornado.web.RequestHandler):
    '''
    This class is a Web service that listens to POST
    requests from an LTI consumer. The module simply echoes
    all the parameters that the consumer passes in.
    
    This class differs from the corresponding classes 
    in lti_candace_provider.py and lti_dill_provider.py
    in that this service participates in a service 
    registration scheme (see lti_event_dispatcher.py).
    Consumers direct all requests to the event dispatcher
    LTI, which forwards to the proper final provider. 
    
    Results from this class are returned to the dispatcher
    via POST. The dispatcher returns the results to the
    originally requesting consumer.
    
    That is: requests to this provider will originate
    not from a browser, but from the event dispatcher LTI. 
     
    The service listens on port 7070 on the server it
    runs on. If running on mono.stanford.edu, the 
    following URL lets you exercise the service:
    https://lagunita.stanford.edu/courses/DavidU/DC1/David_Course/courseware/918c99bd432c4a83ac14e03cbe774fa0/3cdfb888a5bf480a9f17fc0ca1feb53a/2

    If you run it on your own server, and you have
    a sandbox course on Lagunita, you can create 
    an LTI component as described at 
    http://edx.readthedocs.org/projects/edx-partner-course-staff/en/latest/exercises_tools/lti_component.html
    '''

    # Contact of the event dispatcher:
    eventDispatcherURL = 'http://mono.stanford.edu:6969/ltiResponse'

    def post(self):
        '''
        Override the post() method. The
        associated form is expected as a 
        stringified dict in self.request.arguments.
        '''
        # Get a dict of the parameters. Note
        # that one of those parameters will be
        # 'resultToken', which must be returned
        # to the event dispatcher with any 
        # computed results:
        postBodyForm = self.request.body
        postBodyDict = eval(postBodyForm)
        self.echoParmsToEventDispatcher(postBodyDict)
        
    def echoParmsToEventDispatcher(self, paramDict):
        '''
        Write an HTML form back to the calling event dispatcher.
        
        :param postBodyForm: Dict that contains the HTML form attr/val pairs.
        :type postBodyForm: {string : string}
        '''
        paramNames = paramDict.keys()
        paramNames.sort()
        
        # Build a request object... 
        request = httpclient.HTTPRequest(LTIJohnProvider.eventDispatcherURL, method='POST', body=str(paramDict))
        http_client = httpclient.AsyncHTTPClient()
        # ... and ship it:
        ltiResult = http_client.fetch(request, callback=lambda result: None)
        #print('John: delivered result to event dispatcher: %s' % ltiResult)
        
    @classmethod  
    def makeApp(self):
        '''
        Create the tornado application, making it 
        called via http://myServer.stanford.edu:<port>/candace
        '''
        application = tornado.web.Application([
            (r"/john", LTIJohnProvider),
            ])
        return application

if __name__ == "__main__":
    application = LTIJohnProvider.makeApp()
    # Run the app on its port:
    application.listen(7072)

    http_client = httpclient.HTTPClient()
    try:
        # Register this service with lti_event_dispatcher:
        urlRequestPart = "providerName=john&providerURL=http://mono.stanford.edu:7072/john"
        request = httpclient.HTTPRequest("http://mono.stanford.edu:6969/register?%s" % urlRequestPart, method='GET')
        response = http_client.fetch(request)
        print(response.body)
    except httpclient.HTTPError as e:
        # HTTPError is raised for non-200 responses; the response
        # can be found in e.response.
        raise IOError("Error trying to register: " + str(e))    
    
    tornado.ioloop.IOLoop.instance().start()
