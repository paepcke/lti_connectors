'''
Created on Apr 29, 2015

@author: paepcke
'''
import tornado.ioloop
import tornado.web

USE_CENTRAL_EVENT_LOOP = True

class LTIDillProvider(tornado.web.RequestHandler):
    '''
   This class is a Web service that listens to POST
    requests from OpenEdX. The module simply echoes
    all the parameters that OpenEdx passes in. The
    service listens on port 7070 on the server it
    runs on. If running on mono.stanford.edu, the 
    following URL lets you exercise the service:
    https://lagunita.stanford.edu/courses/DavidU/DC1/David_Course/courseware/918c99bd432c4a83ac14e03cbe774fa0/3cdfb888a5bf480a9f17fc0ca1feb53a/2

    If you run it on your own server, and you have
    a sandbox course on Lagunita, you can create 
    an LTI component as described at 
    http://edx.readthedocs.org/projects/edx-partner-course-staff/en/latest/exercises_tools/lti_component.html
    '''

    def post(self):
        '''
        Override the post() method. The
        associated form is available as a 
        dict in self.request.arguments.
        '''
        postBodyForm = self.request.arguments
        #print(str(postBody))
        self.echoParmsToBrowser(postBodyForm)

    def echoParmsToBrowser(self, postBodyForm):
        '''
        Write an HTML form back to the calling browser.
        
        :param postBodyForm: Dict that contains the HTML form attr/val pairs.
        :type postBodyForm: {string : string}
        '''
        paramNames = postBodyForm.keys()
        paramNames.sort()
        self.write('<html><body>')
        self.write('<b>Dill Module Was Invoked With Parameters:</b><br><br>')
        for key in paramNames:
            self.write('<b>%s: </b>%s<br>' % (key, postBodyForm[key]))
        self.write("</body></html>")
        
    @classmethod  
    def makeApp(self):
        '''
        Create the tornado application, making it 
        called via http://myServer.stanford.edu:<port>/dill
        '''
        application = tornado.web.Application([
            (r"/dill", LTIDillProvider),
            ])
        return application

if __name__ == "__main__":
    application = LTIDillProvider.makeApp() 
    # Run the app on its port:
    application.listen(7071)
    tornado.ioloop.IOLoop.instance().start()        