A bridge service that accepts Learning Technology Interchange (LTI)
consumers' requests via POST, and passes them on to a SchoolBus
service. LTI consumers may perform any of three actions: publish to a
topic on the bus, subscribe to, and unsubscribe from bus topics. See
below, and header of src/ltischoolbus/lti_schoolbus_bridge.py for format
details. The description is also available via HTTP once the service
is running. By default the service runs on port 7075.

LTI keys and secrets are kept in a configuration file outside the
github repo. By default that file is expected at
$HOME/.ssh/ltibridge.cnf. See template at
src/ltischoolbus/ltibridge.cnf.example. 

Also under src are some demos that help with debugging LTI requests
in general. For example, the Dill service, when running, will echo LTI
POST requests.

Request messages must be POSTed to this server. Format:
         {
            "key"         : <lti-key>,
            "secret"      : <lti-secret>,
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
