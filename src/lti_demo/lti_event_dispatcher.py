'''
Created on Apr 29, 2015

@author: paepcke
'''

import random
import threading
from tornado import httpclient
import tornado.ioloop
import tornado.web

from tornado.web import asynchronous


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
    
    connectionDictLock = threading.Lock()
    connectionDict     = {}

    def get(self):
        providerName = self.get_argument('providerName', '<noProviderName>')
        providerURL  = self.get_argument('providerURL', '<noProviderURL>')
        LTIEventDispatcher.registeredLTIClasses[providerName] = providerURL
        self.write('You registered successfully, %s.' % providerName)
        
    @asynchronous
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
        resultToken = self.registerConnection(self)
        postBodyForm['resultToken'] = resultToken
        request = httpclient.HTTPRequest(providerURL, method='POST', body=str(postBodyForm))
        http_client = httpclient.AsyncHTTPClient()
        http_client.fetch(request, callback=(lambda res: None))
        
    def registerConnection(self, connection):
        
        LTIEventDispatcher.connectionDictLock.acquire()
        while True:
            randToken = random.random()
            try:
                LTIEventDispatcher.connectionDict[randToken]
            except KeyError:
                LTIEventDispatcher.connectionDict[randToken] = self
                break
        LTIEventDispatcher.connectionDictLock.release()
        return randToken

    @classmethod  
    def makeApp(self):
        application = tornado.web.Application([
            (r"/ltiHandler", LTIEventDispatcher),
            (r"/register", LTIEventDispatcher),
            (r"/ltiResponse", LTIResponseListener)
            ])
        return application

class LTIResponseListener(tornado.web.RequestHandler):
    
    def post(self):
        resultDict = eval(self.request.body)
        resultToken = resultDict['resultToken']
        connection  = LTIEventDispatcher.connectionDict[resultToken]
        
        resNames = resultDict.keys()
        resNames.sort()
        connection.write('<html><body>')
        connection.write('<b>John Module Was Invoked With Parameters:</b><br><br>')
        for key in resNames:
            if key == 'resultToken':
                continue
            connection.write('<b>%s: </b>%s <br>' % (key, resultDict[key]))
        connection.write("</body></html>")
        
        connection.finish()
        del(LTIEventDispatcher.connectionDict[resultToken])
    
if __name__ == "__main__":
    application = LTIEventDispatcher.makeApp() 
    application.listen(6969)
    tornado.ioloop.IOLoop.instance().start()                