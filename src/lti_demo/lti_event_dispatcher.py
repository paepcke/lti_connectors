'''
Created on Apr 29, 2015

@author: paepcke
'''

from tornado import httpclient
import tornado.ioloop
import tornado.web
import urllib


class LTIEventDispatcher(tornado.web.RequestHandler):
    '''
    Untested, and one method incomplete:
    If post() method were completed, this class
    would allow LTI provider modules to register
    themselves by name and URL. Example:
        ('dill', 'http://mono.stanford.edu/dill')
    LTI definitions to OpenEdX would then include
    the custom parameter 'providerName', which would
    be something like 'dill', or 'candace'. 
    All LTI calls from OpenEdX would then go to 
    a single place: this service: 
       http://mono.stanford.edu:7070
      
    '''

    # Must be a class variable, b/c this class gets
    # instantiated every time a request arrives. 
    # In a real system you need to serialize access
    # to this var:
    registeredLTIClasses = {}
    
    noOpMethod = lambda result: None

    def get(self):
        providerName = self.get_argument('providerName', '<noProviderName>')
        providerURL  = self.get_argument('providerURL', '<noProviderURL>')
        LTIEventDispatcher.registeredLTIClasses[providerName] = providerURL
        self.write('You registered successfully, %s.' % providerName)
        
    def post(self):
        postBodyForm = self.request.arguments
        # Obviously would need error checking here;
        # Get destination provider name from custom 
        # parameter 'providerName' (returns a singleton list):
        providerName = postBodyForm['custom_providerName']
        try:
            providerURL  = self.registeredLTIClasses[providerName[0].lower()]
        except KeyError:
            self.write('LTI module %s is not registered with lti_event_dispatcher.' % providerName)
            return
        # ... and POST the postBodyForm to that provider's URL:
        request = httpclient.HTTPRequest(providerURL, method='POST', body=str(postBodyForm))
        http_client = httpclient.AsyncHTTPClient()
        ltiResult = http_client.fetch(request, callback=(lambda res: None))
        #****print('LTI result: %s' % ltiResult)

    @classmethod  
    def makeApp(self):
        application = tornado.web.Application([
            (r"/ltiHandler", LTIEventDispatcher),
            (r"/register", LTIEventDispatcher),
            (r"/ltiResponse", LTIResponseListener)
            ])
        return application

class LTIResponseListener(tornado.web.RedirectHandler):
    
    def __init__(self, eventDispatcherInst):
        self.eventDispatcherInst = eventDispatcherInst
        
    def post(self):
        resultDict = eval(self.request.body)
        resNames = resultDict.keys()
        resNames.sort()
        self.write('<html><body>')
        self.write('<b>John Module Was Invoked With Parameters:</b><br><br>')
        for key in resNames:
            self.eventDispatcherInst.write('<b>%s: </b>%s <br>' % (key, resultDict[key]))
        self.eventDispatcherInst.write("</body></html>")
        
    
    
    
if __name__ == "__main__":
    application = LTIEventDispatcher.makeApp() 
    application.listen(6969)
    tornado.ioloop.IOLoop.instance().start()                