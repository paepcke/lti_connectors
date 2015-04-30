'''
Created on Apr 29, 2015

@author: paepcke
'''

import tornado.ioloop
import tornado.web

class LTIEventDispatcher(tornado.web.RequestHandler):
    '''
    classdocs
    '''

    def __init__(self):
        '''
        Constructor
        '''
        super(LTIEventDispatcher, self).__init__()
        self.registeredLTIClasses = []
        self.application = None

    def registerLTIModule(self, providerName, providerURL):
        self.registeredLTIClasses.append((providerName, providerURL))

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