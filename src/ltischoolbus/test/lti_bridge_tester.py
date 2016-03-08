'''
Created on Jan 21, 2016

@author: paepcke
'''
from __builtin__ import classmethod
import copy
import json
import os
import re
import socket
import subprocess
import sys
import time
import unittest
from unittest.case import skipUnless, skip
from urllib2 import HTTPError, URLError
import urllib2

from redis_bus_python.bus_message import BusMessage
from redis_bus_python.redis_bus import BusAdapter

from ltischoolbus import lti_schoolbus_bridge


# Set to False if you only want to run
# one of the tests, and comment it's
# skipUnless decorator:
TEST_ALL = True


class LtiBridgeTester(unittest.TestCase):
    
    LTI_BRIDGE_SERVICE_PORT = 7075
    LTI_BRIDGE_DELIVERY_PORT = 7076
    LTI_BRIDGE_URL = 'https://%s:%s/schoolbus' % (socket.getfqdn(), LTI_BRIDGE_SERVICE_PORT)
    LTI_DELIVERY_URL = 'https://%s:%s/delivery' % (socket.getfqdn(), LTI_BRIDGE_DELIVERY_PORT)
    # File prefix P for files P.lock and P.txt. P.lock will be
    # used by delivery_rx_server.py to prevent a unittest 
    # from reading the P.txt file before it is fully written.
    # The delivery_rx_server writes any received messages
    # into P.txt, removing P.lock after write is complete.
    # P is CONTENT_LOCK_FILE_PATH_ROOT:
    CONTENT_LOCK_FILE_PATH_ROOT = os.path.join(os.path.dirname(__file__), 'delivery_content_file')
    # Topic to which we assume an LTI component
    DELIVERY_TEST_TOPIC = 'deliveryTest'
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
                           "bus_topic" : DELIVERY_TEST_TOPIC,\
                           "payload" : {\
                		                 "delivery_url" : LTI_DELIVERY_URL \
                		               },\
                           }
 
    
    test_msg_dict_copy = None
                     
    @classmethod
    def setUpClass(cls):
        super(LtiBridgeTester, cls).setUpClass()
        cls.bus = BusAdapter()
        if not is_running('lti_schoolbus_bridge'):
            cls.bridge_was_running = False
            # We assume that the lti bridge executable is 
            # in the parent directory:
            currDir = os.path.dirname(__file__)
            path = os.path.join(currDir, '../lti_schoolbus_bridge.py')
            subprocess.Popen(path, shell=True)
            print('Started lti_schoolbus_bridge.py')
        else:
            cls.bridge_was_running = True
        
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
        sys.stdout.write('testLtiKeyAbsent: ')
        # Remove ltiKey
        self.test_lti_msg_dict.pop('ltiKey')
        with self.assertRaises(HTTPError) as the_exc:
            self.send_to_lti_bridge(self.test_lti_msg_dict)
        # Unauthorized:
        self.assertEqual(401, the_exc.exception.fp.code)
        print('OK')

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testLtiKeyWrong(self):
        sys.stdout.write('testLtiKeyWrong: ')
        self.test_lti_msg_dict['ltiKey'] = 'bluebeard'
        with self.assertRaises(HTTPError) as the_exc:
            self.send_to_lti_bridge(self.test_lti_msg_dict)
        # Unauthorized:
        self.assertEqual(401, the_exc.exception.fp.code)
        print('OK')

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testLtiSecretAbsent(self):
        sys.stdout.write('testLtiSecretAbsent: ')
        # Remove ltiSecret
        self.test_lti_msg_dict.pop('ltiSecret')
        with self.assertRaises(HTTPError) as the_exc:
            self.send_to_lti_bridge(self.test_lti_msg_dict)
        # Unauthorized:
        self.assertEqual(401, the_exc.exception.fp.code)
        print('OK')

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testLtiSecretWrong(self):
        sys.stdout.write('testLtiSecretWrong: ')
        self.test_lti_msg_dict['ltiSecret'] = 'graybeard'
        with self.assertRaises(HTTPError) as the_exc:
            self.send_to_lti_bridge(self.test_lti_msg_dict)
        # Unauthorized:
        self.assertEqual(401, the_exc.exception.fp.code)
        print('OK')

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testBadJsonInPayload(self):
        sys.stdout.write('testBadJsonInPayload: ')        
        self.test_lti_msg_dict['payload'] = 'foo=10&bar=15'
        with self.assertRaises(HTTPError) as the_exc:
            self.send_to_lti_bridge(self.test_lti_msg_dict)
        # Unsupported Media Type:
        self.assertEqual(415, the_exc.exception.fp.code)
        print('OK')

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testNoActionField(self):
        sys.stdout.write('testNoActionField: ')
        self.test_lti_msg_dict.pop('action')
        with self.assertRaises(HTTPError) as the_exc:
            self.send_to_lti_bridge(self.test_lti_msg_dict)
        # Method not allowed:
        self.assertEqual(405, the_exc.exception.fp.code)
        print('OK')

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testNoTargetTopic(self):
        sys.stdout.write('testNoTargetTopic: ')
        self.test_lti_msg_dict.pop('bus_topic')
        with self.assertRaises(HTTPError) as the_exc:
            self.send_to_lti_bridge(self.test_lti_msg_dict)
        # Bad Request:
        self.assertEqual(400, the_exc.exception.fp.code)
        print('OK')

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testNoPayload(self):
        sys.stdout.write('testNoPayload')
        self.test_lti_msg_dict.pop('payload')
        with self.assertRaises(HTTPError) as the_exc:
            self.send_to_lti_bridge(self.test_lti_msg_dict)
        # Bad Request:
        self.assertEqual(400, the_exc.exception.fp.code)
        print('OK')

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')    
    def testNoDeliveryUrlInSubscribe(self):
        sys.stdout.write('testNoDeliveryUrlInSubscribe')
        self.test_subscribe_dict['payload'].pop('delivery_url')
        with self.assertRaises(HTTPError) as the_exc:
            self.send_to_lti_bridge(self.test_subscribe_dict)
        # Bad Request:
        self.assertEqual(400, the_exc.exception.fp.code)
        print('OK')

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testNonSecureDeliveryUrl(self):
        sys.stdout.write('testNonSecureDeliveryUrl: ')
        self.test_subscribe_dict['payload']['delivery_url'] = 'http://%s:%s/schoolbus' % (socket.getfqdn(), 
                                                                                          LtiBridgeTester.LTI_BRIDGE_SERVICE_PORT) 
        with self.assertRaises(HTTPError) as the_exc:
            self.send_to_lti_bridge(self.test_subscribe_dict)
        # Forbidden:
        self.assertEqual(403, the_exc.exception.fp.code)
        print('OK')

    #@skipUnless(TEST_ALL, 'TEST_All not set to True.')
    @unittest.skip('... till SSL is worked out.')
    def testBusMsgDeliveryToLtiModule(self):
        '''
        Check that the delivery_rx_server is running. It pretends
        to be an LTI component that has subscribed to the 
        bus topic set in the test_subscribe_dict, and has an endpoint 
        at LTI_DELIVERY_URL. *****
        '''
        sys.stdout.write('testBusMsgDeliveryToLtiModule: ')
        
        # The delivery_rx_server must be running for this unittest
        # to work:
        if not is_running('delivery_rx_server.py'):
            delivery_server_was_running = False
            delivery_server_path = os.path.join(os.path.dirname(__file__), 'delivery_rx_server.py')
            subprocess.Popen(delivery_server_path)
        else:
            delivery_server_was_running = True
        
        try:
            os.remove(LtiBridgeTester.CONTENT_LOCK_FILE_PATH_ROOT + '.txt')
        except Exception:
            pass
        # Write an empty lock file that the delivery_rx_server will remove
        # when it has written its received msg to disk:
        with open(LtiBridgeTester.CONTENT_LOCK_FILE_PATH_ROOT + '.lock', 'w') as fd:
            fd.write('')
        bus_msg = BusMessage("Delivery test", LtiBridgeTester.DELIVERY_TEST_TOPIC)
        LtiBridgeTester.bus.publish(bus_msg)

        # Wait for delivery_rx_server to receive the msg,
        # and put it's contents into file LtiBridgeTester.CONTENT_LOCK_FILE_PATH_ROOT:
        for i in range(4): #@UnusedVariable
            time.sleep(0.5)
            try:
                open(LtiBridgeTester.CONTENT_LOCK_FILE_PATH_ROOT + '.lock', 'r')
            except:
                # Lock file is gone, so delivery_rx_server has written into the .txt file:
                with open(LtiBridgeTester.CONTENT_LOCK_FILE_PATH_ROOT + '.txt', 'r') as fd:
                    all_info = fd.readlines()
                    print(all_info)
                    correct = '[\'{"time" : "2016-03-07T16:07:32", "ltiKey" : "ltiKey", "ltiSecret" : "ltiSecret", "bus_topic" : "deliveryTest", "payload" : "Delivery test"}\']'
                    self.assertEqual(correct, str(all_info))
                    print('OK')
                    try:
                        os.remove(LtiBridgeTester.CONTENT_LOCK_FILE_PATH_ROOT + '.lock')
                    except:
                        self.fail("Delivery to LTI worked, but could not remove lock file.")
                    return
                
                    try:
                        os.remove(LtiBridgeTester.CONTENT_LOCK_FILE_PATH_ROOT + '.txt')
                    except:
                        self.fail("Delivery to LTI worked, but could not remove content file.")
                    return
        # Tried multiple times, but the file didn't appear:
        self.fail('Delivery to LTI did not arrive.')
        

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testUrlQueryPartNonEmpty(self):
        sys.stdout.write('testUrlQueryPartNonEmpty: ')
        self.test_subscribe_dict['payload']['delivery_url'] = '%s/schoolbus/?foo=10' % LtiBridgeTester.LTI_BRIDGE_URL
        with self.assertRaises(HTTPError) as the_exc:
            self.send_to_lti_bridge(self.test_subscribe_dict)
        # Conflict:
        self.assertEqual(409, the_exc.exception.fp.code)
        print('OK')

    @skipUnless(TEST_ALL, 'TEST_All not set to True.')
    def testUnknownActionCommand(self):
        sys.stdout.write('testUnknownActionCommand: ')
        self.test_lti_msg_dict['action'] = 'jumpOffBridge'
        with self.assertRaises(HTTPError) as the_exc:
            self.send_to_lti_bridge(self.test_lti_msg_dict)
        # Not Implemented
        self.assertEqual(501, the_exc.exception.fp.code)
        print('OK')

    def send_to_lti_bridge(self, data_dict):
        
        request = urllib2.Request(LtiBridgeTester.LTI_BRIDGE_URL, data_dict, {'Content-Type': 'application/json'})
        response = urllib2.urlopen(request, json.dumps(data_dict)) #@UnusedVariable
        return True
        #for res in response:
        #    print(res)

def is_running(process):
    '''
    Return true if Linux process with given name is
    running.
    
    :param process: process name as appears in ps -axw
    :type process: string
    '''
    search_proc = subprocess.Popen(['ps', 'axw'],stdout=subprocess.PIPE)
    for ps_line in search_proc.stdout:
        if re.search(process, ps_line):
            return True 
    return False


if __name__ == "__main__":
    #import sys;sys.argv = ['', 'Test.testLtiKeyAbsent']
    unittest.main()