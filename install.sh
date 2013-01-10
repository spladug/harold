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
mkdir -p /opt/harold/lib
mkdir -p /opt/harold/etc
cd /opt/harold/
git clone https://github.com/spladug/harold.git /opt/harold/lib/

# copy the upstart scripts into place
cp /opt/harold/lib/upstart/*.conf /etc/init/

# done!
cat <<END
Harold is installed. please create and configure configuration files for harold
instances in /opt/harold/etc/____.ini and start harold via upstart as follows:

    start harold-startup

END
