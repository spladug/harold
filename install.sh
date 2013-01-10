#!/bin/bash

if [ $EUID -ne 0 ]; then
    echo "you must be root"
fi

# prerequisite packages
apt-get install git-core python-twisted python-twisted-words python-twisted-web

# user to run as
addgroup --system harold
adduser --system harold

# the repo itself
cd /opt
git clone https://github.com/spladug/harold.git

# copy the upstart scripts into place
cp /opt/harold/upstart/*.conf /etc/init/

# done!
cat <<END
harold is installed. please create and configure /opt/harold/harold.ini and
start harold via upstart ("start harold").
END
