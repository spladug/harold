#!/usr/bin/python

import ConfigParser
import getpass
import json
import requests
from requests.auth import HTTPBasicAuth
import urlparse

from harold.plugins.github import REPOSITORY_PREFIX


def _make_hooks_url(repo, endpoint=None):
    path_fragments = ["/repos", repo, "hooks"]
    if endpoint:
        path_fragments.append(endpoint)

    return urlparse.urlunsplit((
        "https",
        "api.github.com",
        "/".join(path_fragments),
        None,
        None
    ))

# figure out which repos we care about
repositories = []
parser = ConfigParser.ConfigParser()
with open("harold.ini", "r") as f:
    parser.readfp(f)

for section in parser.sections():
    if not section.startswith(REPOSITORY_PREFIX):
        continue
    repositories.append(section[len(REPOSITORY_PREFIX):])

print "I will ensure webhooks are registered for:"
for repo in repositories:
    print "  - " + repo
print

netloc = raw_input("Harold GitHub Webhook Host: ")
username = raw_input("GitHub Username: ")
password = getpass.getpass("GitHub Password: ")
session = requests.session(auth=HTTPBasicAuth(username, password),
                           verify=True
                          )

http_secret = parser.get("harold:plugin:http", "secret")
webhook_url = urlparse.urlunsplit((
    "http",
    netloc,
    "/harold/github/" + http_secret,
    None,
    None
))

DESIRED_EVENTS = ["push", "pull_request"]
for repo in repositories:
    print repo

    # list existing hooks
    hooks_response = session.get(_make_hooks_url(repo))
    hooks_response.raise_for_status()
    hooks = hooks_response.json

    # determine if we're already configured / destroy non-conforming hooks
    found_valid_hook = False
    for hook in hooks:
        if (hook["config"]["url"] != webhook_url or
            hook["events"] != DESIRED_EVENTS or
            found_valid_hook):
            print "  Deleting non-conforming hook %d" % hook["id"]
            response = session.delete(_make_hooks_url(repo, str(hook["id"])))
            response.raise_for_status()
        else:
            print "  Found existing valid hook (%d)" % hook["id"]
            found_valid_hook = True

    if found_valid_hook:
        continue

    print "  Registering hook"
    response = session.post(
        _make_hooks_url(repo),
        data=json.dumps(dict(
            name="web",
            config=dict(
                url=webhook_url,
            ),
            events=[
                "push",
                "pull_request",
            ],
            active=True,
        )),
    )
    response.raise_for_status()
