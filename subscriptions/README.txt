This directory is where file schoolbus_subscriptions.json is kept. It
is not uploaded to Github, because every installation will have its
own subscriptions of LTI consumers to SchoolBus messages. However, no
secrets are kept in this file. It is simply a mapping of SchoolBus
topics to a list of URLs to which bus message are to be delivered. The
keys and secrets associated with each topic are by default kept in
$HOME/.ssh/ltibridge.cnf.

The schoolbus_subscriptions.json file is not created by hand! It is
managed by an instance of jsonfiledict.JsonFileDict in
src/ltischoolbus/lti_schoolbus_bridge.py.
