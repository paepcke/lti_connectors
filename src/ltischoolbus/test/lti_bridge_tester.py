'''
Created on Jan 21, 2016

@author: paepcke
'''
from __builtin__ import classmethod
import copy
import json
import unittest
from urllib2 import HTTPError, URLError
import urllib2

from redis_bus_python.redis_bus import BusAdapter
from unittest.case import skipUnless

# Set to False if you only want to run
# one of the tests, and comment it's
# skipUnless decorator:

TEST_ALL = True

class LtiBridgeTester(unittest.TestCase):
    
    TEST_URL = 'https://mono.stanford.edu:7075/schoolbus'
    TEST_MSG_DICT = {"ltiKey" : "ltiKey",\
                     "ltiSecret" : "ltiSecret",\
                     "action" : "publish",\
    			     "bus_topic" :  "studentAction",\
    			     "payload" :    {"event_type": "problem_check",\
    					              "resource_id": "i4x://HumanitiesSciences/NCP-101/problem/__61",
    					        	  "student_id": "d4dfbbce6c4e9c8a0e036fb4049c0ba3",
    					        	  "answers": {"i4x-HumanitiesSciences-NCP-101-problem-_61_2_1": ["choice_3", "choice_4"]},
    					        	  "result": "False",
    					        	  "course_id": "HumanitiesSciences/NCP-101/OnGoing"
    				                 }
                     }
    TEST_SUBSCRIBE_DICT = {"ltiKey" : "ltiKey",\
                           "ltiSecret" : "ltiSecret",\
                           "action" : "subscribe",\
                           "bus_topic" : "studentAction",\
                           "payload" : {\
                		                 "delivery_url" : "https://myMachine.myDomain.edu"\
                		               },\
                           }
 
    
    test_msg_dict_copy = None
                     
    @classmethod
    def setUpClass(cls):
        super(LtiBridgeTester, cls).setUpClass()
        cls.bus = BusAdapter()
        
    @classmethod
    def tearDownClass(cls):
        unittest.TestCase.tearDownClass()
        cls.bus.close()
        
    def setUp(self):
        unittest.TestCase.setUp(self)
        # Fresh copy of a correct msg:
        self.test_lti_msg_dict = copy.deepcopy(LtiBridgeTester.TEST_MSG_DICT)
        self.test_subscribe_dict = copy.deepcopy(LtiBridgeTester.TEST_SUBSCRIBE_DICT)

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testLtiKeyAbsent(self):
        # Remove ltiKey
        self.test_lti_msg_dict.pop('ltiKey')
        with self.assertRaises(HTTPError) as the_exc:
            self.send_from_lti(self.test_lti_msg_dict)
        # Unauthorized:
        self.assertEqual(401, the_exc.exception.fp.code)

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testLtiKeyWrong(self):
        self.test_lti_msg_dict['ltiKey'] = 'bluebeard'
        with self.assertRaises(HTTPError) as the_exc:
            self.send_from_lti(self.test_lti_msg_dict)
        # Unauthorized:
        self.assertEqual(401, the_exc.exception.fp.code)

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testLtiSecretAbsent(self):
        # Remove ltiSecret
        self.test_lti_msg_dict.pop('ltiSecret')
        with self.assertRaises(HTTPError) as the_exc:
            self.send_from_lti(self.test_lti_msg_dict)
        # Unauthorized:
        self.assertEqual(401, the_exc.exception.fp.code)

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testLtiSecretWrong(self):
        self.test_lti_msg_dict['ltiSecret'] = 'graybeard'
        with self.assertRaises(HTTPError) as the_exc:
            self.send_from_lti(self.test_lti_msg_dict)
        # Unauthorized:
        self.assertEqual(401, the_exc.exception.fp.code)

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testBadJsonInPayload(self):
        self.test_lti_msg_dict['payload'] = 'foo=10&bar=15'
        with self.assertRaises(HTTPError) as the_exc:
            self.send_from_lti(self.test_lti_msg_dict)
        # Unsupported Media Type:
        self.assertEqual(415, the_exc.exception.fp.code)

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testNoActionField(self):
        self.test_lti_msg_dict.pop('action')
        with self.assertRaises(HTTPError) as the_exc:
            self.send_from_lti(self.test_lti_msg_dict)
        # Method not allowed:
        self.assertEqual(405, the_exc.exception.fp.code)

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testNoTargetTopic(self):
        self.test_lti_msg_dict.pop('bus_topic')
        with self.assertRaises(HTTPError) as the_exc:
            self.send_from_lti(self.test_lti_msg_dict)
        # Bad Request:
        self.assertEqual(400, the_exc.exception.fp.code)

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testNoPayload(self):
        self.test_lti_msg_dict.pop('payload')
        with self.assertRaises(HTTPError) as the_exc:
            self.send_from_lti(self.test_lti_msg_dict)
        # Bad Request:
        self.assertEqual(400, the_exc.exception.fp.code)

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')    
    def testNoDeliveryUrlInSubscribe(self):
        self.test_subscribe_dict['payload'].pop('delivery_url')
        with self.assertRaises(HTTPError) as the_exc:
            self.send_from_lti(self.test_subscribe_dict)
        # Bad Request:
        self.assertEqual(400, the_exc.exception.fp.code)

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testNonSecureDeliveryUrl(self):
        self.test_subscribe_dict['payload']['delivery_url'] = 'http://mono.stanford.edu:7075/schoolbus'
        with self.assertRaises(HTTPError) as the_exc:
            self.send_from_lti(self.test_lti_msg_dict)
        # Forbidden:
        self.assertEqual(403, the_exc.exception.fp.code)

    skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testUrlQueryPartNonEmpty(self):
        self.test_subscribe_dict['payload']['delivery_url'] = 'https://mono.stanford.edu:7075/schoolbus/?foo=10'
        with self.assertRaises(HTTPError) as the_exc:
            self.send_from_lti(self.test_subscribe_dict)
        # Conflict:
        self.assertEqual(409, the_exc.exception.fp.code)

    #@skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testUnknownActionCommand(self):
        self.test_lti_msg_dict['action'] = 'jumpOffBridge'
        with self.assertRaises(HTTPError) as the_exc:
            self.send_from_lti(self.test_lti_msg_dict)
        # Not Implemented
        self.assertEqual(501, the_exc.exception.fp.code)

    def send_from_lti(self, data_dict):
        
        request = urllib2.Request(LtiBridgeTester.TEST_URL, data_dict, {'Content-Type': 'application/json'})
        response = urllib2.urlopen(request, json.dumps(data_dict)) #@UnusedVariable
        return True
        #for res in response:
        #    print(res)



if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testLtiKeyAbsent']
    unittest.main()