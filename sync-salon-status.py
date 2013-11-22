#!/usr/bin/python

import getpass
import itertools
import os
import sys
import urllib
import urlparse

import requests

from requests.auth import HTTPBasicAuth

from harold.conf import HaroldConfiguration
from harold.plugins.database import DatabaseConfig
from harold.plugins.github import GitHubConfig, SalonDatabase


class SynchronousDatabase(object):
    """A class that mimics twisted's ADBAPI but is synchronous."""

    def __init__(self, config):
        self.module, kwargs = config.get_module_and_params()
        self.connection = self.module.connect(**kwargs)

    def runQuery(self, *args, **kwargs):
        cursor = self.connection.cursor()
        cursor.execute(*args, **kwargs)
        return cursor.fetchall()

    def runOperation(self, *args, **kwargs):
        cursor = self.connection.cursor()
        cursor.execute(*args, **kwargs)
        self.connection.commit()

    def __del__(self):
        self.connection.close()


def make_pullrequest_url(repo, state):
    return urlparse.urlunsplit((
        "https",
        "api.github.com",
        "/".join(["/repos", repo, "pulls"]),
        urllib.urlencode({
            "state": state,
        }),
        None
    ))


def make_comments_url(repo):
    return urlparse.urlunsplit((
        "https",
        "api.github.com",
        "/".join(["/repos", repo, "issues", "comments"]),
        urllib.urlencode({
            "sort": "created",
            "direction": "desc",
        }),
        None
    ))


def fetch_paginated(url):
    scheme, netloc, path, query, fragment = urlparse.urlsplit(url)
    params = urlparse.parse_qs(query)
    params["per_page"] = 100

    for page in itertools.count(start=1):
        params["page"] = page
        new_querystring = urllib.urlencode(params)
        paginated_url = urlparse.urlunsplit((scheme, netloc, path,
                                             new_querystring, fragment))

        response = session.get(paginated_url)
        response.raise_for_status()

        if not response.json:
            break

        for item in response.json:
            yield item


# config file is an expected argument
bin_name = os.path.basename(sys.argv[0])
if len(sys.argv) != 2:
    print >> sys.stderr, "USAGE: %s INI_FILE" % bin_name
    sys.exit(1)

config_file = sys.argv[1]
try:
    config = HaroldConfiguration(config_file)
except Exception as e:
    print >> sys.stderr, "%s: failed to read config file %r: %s" % (
        bin_name,
        config_file,
        e,
    )
    sys.exit(1)

# connect to db
gh_config = GitHubConfig(config)
db_config = DatabaseConfig(config)
database = SalonDatabase(SynchronousDatabase(db_config))

# figure out which repos we care about
repositories = gh_config.repositories_by_name.keys()

if not repositories:
    print "No repositories to sync!"
    sys.exit(0)

print "I will synchronize salon status for:"
for repo in repositories:
    print "  - " + repo
print

# get auth credentials
username = raw_input("GitHub Username: ")
password = getpass.getpass("GitHub Password: ")

# set up an http session
session = requests.session()
session.auth = HTTPBasicAuth(username, password)
session.verify = True
session.headers["User-Agent"] = "Harold-by-@spladug"

# query and sync the database
for repo in repositories:
    print repo

    # synchronize pull requests
    pull_requests = itertools.chain(
        fetch_paginated(make_pullrequest_url(repo, "open")),
        fetch_paginated(make_pullrequest_url(repo, "closed")),
    )
    for pull_request in pull_requests:
        print "  %s#%s" % (repo, pull_request["number"])
        database.process_pullrequest(pull_request, repository=repo)

    # synchronize comments
    for comment in fetch_paginated(make_comments_url(repo)):
        print "  %s comment #%d" % (repo, comment["id"])
        database.process_comment(comment)
