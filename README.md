A bridge service that accepts Learning Technology Interchange (LTI)
consumers' requests via POST, and passes them on to a SchoolBus
service. LTI Consumers may also subscribe to SchoolBus topics.

Overview:

LTI consumers may perform any of three actions:

  - publish to a SchoolBus topic on the bus,
  - subscribe to, and
  - unsubscribe from bus topics.

See below, and also the header of
src/ltischoolbus/lti_schoolbus_bridge.py for POST body format
details. A service description is also available via HTTPS GET once
the lti_schoolbus_bridge service is running. By default the service
runs on port 7075.

As part of an LTI consumer's subscription to a SchoolBus topic, the
consumer provides a delivery URL. The bridge service will subscribe to
the requested topic on the LTI consumer's behalf. Whenever a message
arrives from the bus, the bridge forwards it to all LTI consumers that
previously subscribed to the topic. Delivery of the message is via the
delivery URL provided with the LTI consumer's subscription. The
delivery follows LTI 1.1 conventions.

LTI keys and secrets are kept in a configuration file outside the
github repo. By default that file is expected at
$HOME/.ssh/ltibridge.cnf. See template at
src/ltischoolbus/ltibridge.cnf.example.

Subscriptions are kept in
<projRoot>/subscriptions/lti_bus_subscriptions.json. When the bridge
service is started, it reads this file. So subscriptions survive
service stop/start cycles. Or one can manually edit this file to
remove or add subscriptions.

Note that under <projRoot>/src are some demos that help with debugging LTI
requests in general. For example, the Dill service, when running, will
echo LTI POST requests.

Formats:

Request messages must be POSTed to this server. Format:
         {
            "ltiKey"      : <lti-key>,
            "ltiSecret"   : <lti-secret>,
            "action"      : {"publish" | "subscribe" | "unsubscribe"},
            "bus_topic"   : <schoolbus topic>>
            "payload"     :
            {
            "course_id": course_id,
            "resource_id": problem_id,
            "student_id": anonymous_id_for_user(user, None),
            "answers": answers,
            "result": is_correct,
            "event_type": event_type,
            "target_topic" : schoolbus_topic
            }
        }


The payload may be anything the sender desires. the Bridge does not
process the payload, other than packaging it into a SchoolBus
message. 

Messages from the bus to the LTI consumer are POSTed to the
delivery URL specified during the consumer's subscription process.
Example:

            {
	        "ltiKey" : "myKey",
		"ltiSecret" : "mySecret",
                "time"   : "ISO time string",
                "bus_topic"  : "SchoolBus topic of bus message",
                "payload": "message's 'content' field"
            }    


Again, the payload may hold any content.

The test service
<projRoot>/src/ltischoolbus/test/delivery_rx_server.py can be run from
the command line. It acts like an LTI consumer delivery end point. For
testing one can use http://hurl.it, where POST requests can be created
and fired.

Or, use Python to exercise the lti_schoolbus_bridge.py and
delivery_rx_server.py serivces:

import requests

# Msg from LTI consumer to Bridge: subscribe to topic 'studentAction',
# delivering message from the SchoolBus to
# https://taffy:7076/delivery:

payload_subscribe = {"ltiKey": "ltiKey", "ltiSecret": "ltiSecret", "bus_topic": "studentAction", "action": "subscribe", "payload": {"delivery_url": "https://taffy:7076/delivery"}}

# Msg from LTI consumer to Bridge: publish a msg to the SchoolBus:
r = requests.post('https://trio:7075/schoolbus', data = json.dump(payload_subscribe), verify=False))

payload_pub = {"ltiKey": "ltiKey", "ltiSecret": "ltiSecret", "bus_topic": "studentAction", "action": "publish", "payload": "Hello from some LTI consumer."}

r = requests.post('https://trio:7075/schoolbus', data = json.dumps(payload_pub), verify=False)


# -----------------------

# Or debug the test delivery separately, send a message to the
# delivery test server as would normally be originated by the Bridge
# server when a message arrives from the SchoolBus:

payload_delivery = {"ltiKey": "ltiKey", "ltiSecret": "ltiSecret","bus_topic": "studentAction", "action": "publish", "payload": "Hello from the SchoolBus."}

r = requests.post('https://trio:7076/delivery', data = json.dumps(payload_delivery), verify=False)
