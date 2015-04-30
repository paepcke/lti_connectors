'''
Created on Apr 29, 2015

@author: paepcke
'''

import tornado.ioloop
import tornado.web

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

    def __init__(self):
        '''
        Initialize a dict that maps registered
        LTI service names to their URLs.
        '''
        super(LTIEventDispatcher, self).__init__()
        self.registeredLTIClasses = {}

    def get(self):
        providerName = self.get_argument('providerName', '<noProviderName>')
        providerURL  = self.get_argument('providerURL', '<noProviderURL>')
        self.registeredLTIClasses[providerName] = providerURL
        
    def post(self):
        postBodyForm = self.request.arguments
        # Obviously would need error checking here;
        # Get destination provider name from custom 
        # parameter 'providerName':
        providerName = postBodyForm['providerName']
        providerURL  = self.registeredLTIClasses[providerName]
        # ... and POST the postBodyForm to that URL.

    @classmethod  
    def makeApp(self):
        application = tornado.web.Application([
            (r"/ltiHandler", LTIEventDispatcher),
            ])
        return application

if __name__ == "__main__":
    application = LTIEventDispatcher.makeApp() 
    application.listen(7070)
    tornado.ioloop.IOLoop.instance().start()                