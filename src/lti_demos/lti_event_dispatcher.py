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
    This class, together with lti_john_via_event_loop.py
    illustrates how a central request dispatcher can
    forward requests from LTI consumer to provider via
    indirection. The producer generates results, which
    are passed back to the consumer.
    
    The LTIEventDispatcher maintains a class level
    dict where providers register when they go online.
    Registration matches a service name to a URL where
    the respective provider accepts POST requests.
    
    The consumer is aware of only a single LTI: the dispatcher.
    All requests are directed to that dispatch LTI (i.e. instances
    of this class.) Part of the request is the name of the
    destination service. From the registration process the
    dispatcher knows which service name points to which actual
    LTI service URL. 
    
    Once such a service request is forwarded to the service,
    the service operates for as long as necessary to generate
    a result. That result is returned to the dispatcher, which 
    in turn returns the result to the LTI consumer.
    
    Two classes are involved here: this dispatcher, and a class
    LTIResponseListener whose instances listen for the results
    of services. 
    
    '''

    # Dict where registered service mappings are kept: service
    # name to service URL. Must be a class variable, b/c this class gets
    # instantiated every time a request arrives from an LTI consumer. 

    registeredLTIClasses = {}
    registrationLock     = threading.Lock()
    

    # Dict to keep open connections to LTI consumer until
    # the LTI service to which a request is forwarded returns
    # a result:
    connectionDict     = {}
    connectionDictLock = threading.Lock()

    def get(self):
        '''
        The GET method type is used by services to register
        themselves when they come online. 
        
        The expected GET parameters are:
        
        :param providerName: service name by which the registering service
               is known to the LTI consumer(s)
        :type providerName: string 
        
        '''
        # Grab provider name and URL from the URL parameters:
        providerName = self.get_argument('providerName', '<noProviderName>')
        providerURL  = self.get_argument('providerURL', '<noProviderURL>')
        
        # Register the service in the dict class var,
        # protecting against further requests arriving while
        # we manipulate the dict:
        LTIEventDispatcher.registrationLock.acquire()
        LTIEventDispatcher.registeredLTIClasses[providerName] = providerURL
        LTIEventDispatcher.registrationLock.release()
        
        # Write back to the service to confirm success:
        self.write('You registered successfully, %s.' % providerName)
        
    @asynchronous
    def post(self):
        '''
        POST type HTTP methods are used by the LTI consumer(s) to 
        submit a request to some service, passing an arbitrary number
        of parameters. The @asynchronous decorator tells Tornado
        not to close the HTTP connection when this method returns. 
        
        The one required parameter is:
        
        :param custom_providerName: name of the service to which this 
             request is to be forwarded.
        :type custom_providerName: string
        
        '''
        
        postBodyForm = self.request.arguments
        # Obviously would need error checking here;
        # for missing service name. Omitted for clarity.
        # Get destination provider name from custom 
        # parameter 'custom_providerName' (returns a singleton list):
        providerName = postBodyForm['custom_providerName']
        try:
            providerURL  = self.registeredLTIClasses[providerName[0].lower()]
        except KeyError:
            self.write('LTI module %s is not registered with lti_event_dispatcher.' % providerName)
            return

        # ... and POST the postBodyForm to that provider's URL:
        # Generate a unique token that under which we remember
        # this HTTP connection to the originating consumer. The
        # token is passed to the target provider. The provider includes
        # the token when it asynchronously returns results:
         
        resultToken = self.registerConnection(self)

        # Add parameter 'resultToken' to the parameters that were
        # included in the consumer's request:
        postBodyForm['resultToken'] = resultToken
        
        # Issue a POST request to the service, not waiting for
        # a response:
        request = httpclient.HTTPRequest(providerURL, method='POST', body=str(postBodyForm))
        http_client = httpclient.AsyncHTTPClient()
        
        # Asynch calls require a callback function, which we make into a no-op:
        http_client.fetch(request, callback=(lambda res: None))
        
    def registerConnection(self, connection):
        '''
        Remembers an open incoming connection from an
        LTI consumer, so that results from LTI providers
        that will arrive later can be forwarded back to 
        the consumer.
        
        :param connection: an LTIEventDispatcher instance that embodies the connection. 
        :type connection: LTIEventDispatcher
        '''
        
        LTIEventDispatcher.connectionDictLock.acquire()
        # Look for an unused token to use for a dict key,
        # and that will be provided to the service to identify
        # its return parms:
        
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
        '''
        Register classes with Tornado: POSTs to http://<domain>:6969/ltiHandler
        and GETs to http://<domain>:6969/register will trigger instantiation of
        the LTIEventDispatcher class.
        
        Class LTIResponseListener is instantiated whenever an LTI provider
        asynchronously returns a result: a POST to http://<domain>:6969/ltiResponse. 
        
        '''
        
        application = tornado.web.Application([
            (r"/ltiHandler", LTIEventDispatcher),
            (r"/register", LTIEventDispatcher),
            (r"/ltiResponse", LTIResponseListener)
            ])
        return application

class LTIResponseListener(tornado.web.RequestHandler):
    '''
    Instantiated whenever an LTI provider service returns
    a result via a POST request. At least one POST parameter
    is required:
    
    :param resultToken: a token passed to the provider when the 
         original request was forwarded to it. 
    :type resultToken: string
    '''
    
    def post(self):
        # The POST body is expected to be a dict mapping
        # param names to values. The body is a string that
        # evaluates to a dict:
        resultDict = eval(self.request.body)
        resultToken = resultDict['resultToken']
        
        # Find the open connection that is awaiting the
        # result. A real system would check for presence of 
        # the required resultToken key:
        connection  = LTIEventDispatcher.connectionDict[resultToken]
        
        resNames = resultDict.keys()
        resNames.sort()
        
        # Return the results from the service to the consumer
        # that originally issued the request:
         
        connection.write('<html><body>')
        connection.write('<b>John Module Was Invoked With Parameters:</b><br><br>')
        for key in resNames:
            if key == 'resultToken':
                continue
            connection.write('<b>%s: </b>%s <br>' % (key, resultDict[key]))
        connection.write("</body></html>")
    
        # Indicate to Tornado that the connection can
        # now be closed:    
        connection.finish()
        
        # Remove the connection from the connection dict:
        del(LTIEventDispatcher.connectionDict[resultToken])
    
if __name__ == "__main__":
    application = LTIEventDispatcher.makeApp() 
    application.listen(6969)
    tornado.ioloop.IOLoop.instance().start()                