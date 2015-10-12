'''
Created on Apr 29, 2015

@author: paepcke
'''
import tornado.ioloop
import tornado.web
from tornado import httpserver

import ssl 

USE_CENTRAL_EVENT_LOOP = True

class LTIDillProvider(tornado.web.RequestHandler):
    '''
   This class is a Web service that listens to POST
    requests from OpenEdX. The module simply echoes
    all the parameters that OpenEdx passes in. The
    service listens on port 7071 on the server it
    runs on. If running on mono.stanford.edu, the 
    following URL lets you exercise the service:
    https://lagunita.stanford.edu/courses/DavidU/DC1/David_Course/courseware/918c99bd432c4a83ac14e03cbe774fa0/3cdfb888a5bf480a9f17fc0ca1feb53a/2

    If you run it on your own server, and you have
    a sandbox course on Lagunita, you can create 
    an LTI component as described at 
    http://edx.readthedocs.org/projects/edx-partner-course-staff/en/latest/exercises_tools/lti_component.html
    
    Or: use https://www.hurl.it/ with URL: https://mono.stanford.edu:7071/dill
         If you use the GET method there, setting parms to foo=10, you should get an 
         echo that says:
         <html>
            <body>GET method was called: {'foo': ['10']}.</body>
         </html>
         
         If you use the POST method with the same parm, you should get
         <html>
    		<body>
    		  <b>Dill Module Was Invoked With Parameters:</b>
    		  <br>
    		    <br>
    		      <b>foo: </b>['10']
    		      <br>
            </body>
    	 </html>
    '''

    def get(self):
        getParms = self.request.arguments
        self.write("<html><body>GET method was called: %s.</body></html>" %str(getParms))


    def post(self):
        '''
        Override the post() method. The
        associated form is available as a 
        dict in self.request.arguments.
        '''
        postBodyForm = self.request.arguments
        #print(str(postBody))
        #self.write('<!DOCTYPE html><html><body><script>document.getElementById("ltiFrame-i4x-DavidU-DC1-lti-2edb4bca1198435cbaae29e8865b4d54").innerHTML = "Hello iFrame!"</script></body></html>"');    

        self.echoParmsToEventDispatcher(postBodyForm)

    def echoParmsToEventDispatcher(self, postBodyForm):
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
    # We need an SSL capable HTTP server:
    # For configuration without a cert, add "cert_reqs"  : ssl.CERT_NONE
    # to the ssl_options (though I haven't tried it out.):

    http_server = tornado.httpserver.HTTPServer(application,
                                                ssl_options={"certfile": "/home/paepcke/.ssl/MonoCertSha2Expiration2018/mono_stanford_edu_cert.cer",
                                                             "keyfile" : "/home/paepcke/.ssl/MonoCertSha2Expiration2018/mono.stanford.edu.key"
    })
    # Run the app on its port:
    # Instead of application.listen, as in non-SSL
    # services, the http_server is told to listen:
    #*****application.listen(7071)
    http_server.listen(7071)
    tornado.ioloop.IOLoop.instance().start()        