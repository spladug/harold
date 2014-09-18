#!/usr/bin/python

import ConfigParser
import getpass
import json
import requests
from requests.auth import HTTPBasicAuth
import os
import urlparse
import sys

from harold.plugins.github import REPOSITORY_PREFIX


def yesno(prompt, default):
    while True:
        input = raw_input(prompt)
        if not input:
            return default

        input = input.lower()
        if input in ("y", "yes"):
            return True
        elif input in ("n", "no"):
            return False


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


def main():
    # config file is an expected argument
    bin_name = os.path.basename(sys.argv[0])
    if len(sys.argv) != 2:
        print >> sys.stderr, "USAGE: %s INI_FILE" % bin_name
        sys.exit(1)

    config_file = sys.argv[1]
    try:
        parser = ConfigParser.ConfigParser()
        with open(config_file, "r") as f:
            parser.readfp(f)
    except Exception as e:
        print >> sys.stderr, "%s: failed to read config file %r: %s" % (
            bin_name,
            config_file,
            e,
        )
        sys.exit(1)

    # figure out which repos we care about
    repositories = []

    for section in parser.sections():
        if not section.startswith(REPOSITORY_PREFIX):
            continue
        repositories.append(section[len(REPOSITORY_PREFIX):])

    if not repositories:
        print "No repositories to register with!"
        sys.exit(0)

    delete_unknown_hooks = yesno(
        "Should I delete unknown webhooks? [Y/n] ", default=True)

    print "I will ensure webhooks are registered for:"
    for repo in repositories:
        print "  - " + repo
    print

    netloc = raw_input("Harold GitHub Webhook Netloc: ")

    print
    print "Please enter a GitHub personal access token (found at Settings >>"
    print "Applications on GitHub) with the admin:repo_hook scope authorized"
    token = getpass.getpass("Token: ").strip()

    session = requests.session()
    session.auth = HTTPBasicAuth(token, "x-oauth-basic")
    session.verify = True
    session.headers["User-Agent"] = "Harold-by-@spladug"

    http_secret = parser.get("harold:plugin:http", "secret")
    webhook_url = urlparse.urlunsplit((
        "http",
        netloc,
        "/harold/github/" + http_secret,
        None,
        None
    ))

    DESIRED_EVENTS = ["push", "pull_request", "issue_comment"]
    for repo in repositories:
        print repo

        # list existing hooks
        hooks_response = session.get(_make_hooks_url(repo))
        hooks_response.raise_for_status()
        hooks = hooks_response.json()

        # determine if we're already configured / destroy non-conforming hooks
        found_valid_hook = False
        for hook in hooks:
            # ensure this is a webhook and it was meant for harold
            old_url = hook["config"].get("url", "")
            if "harold" not in old_url:
                continue

            delete_hook = False

            if old_url == webhook_url:
                if hook["events"] != DESIRED_EVENTS:
                    print "  Deleting non-conforming hook %d" % hook["id"]
                    delete_hook = True
                elif found_valid_hook:
                    print "  Deleting duplicate hook %d" % hook["id"]
                    delete_hook = True
                else:
                    print "  Found existing valid hook (%d)" % hook["id"]
                    found_valid_hook = True
            else:
                if delete_unknown_hooks:
                    print "  Deleting unrecognized hook %d" % hook["id"]
                    delete_hook = True
                else:
                    print "  Skipping unrecognized hook %d" % hook["id"]

            if delete_hook:
                response = session.delete(_make_hooks_url(repo, str(hook["id"])))
                response.raise_for_status()

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
                events=DESIRED_EVENTS,
                active=True,
            )),
        )
        response.raise_for_status()
