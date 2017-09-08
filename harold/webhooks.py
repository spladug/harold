#!/usr/bin/python

import argparse
import getpass
import glob
import json
import posixpath
import socket
import sys
import urlparse

import requests
from requests.auth import HTTPBasicAuth

from harold.conf import HaroldConfiguration
from harold.plugins.github import GitHubConfig
from harold.plugins.http import HttpConfig


def get_netloc(url):
    return urlparse.urlparse(url).netloc


def guess_local_address():
    hostname = socket.gethostname()
    fqdn = socket.getfqdn()
    if fqdn != hostname:
        return fqdn

    # "open" a dgram connection to a public ip address to get our outbound ip
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.connect(("8.8.8.8", 53))
    local_ip = sock.getsockname()[0]
    return local_ip


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


def configure_webhooks_for_instance(access_token, config_filename, dry_run):
    print "Processing %s" % config_filename
    harold_config = HaroldConfiguration(config_filename)

    gh_config = GitHubConfig(harold_config)
    repositories = gh_config.repositories_by_name.keys()
    if not repositories:
        print "  No repositories to register with!"
        return

    http_config = HttpConfig(harold_config)
    root = urlparse.urlparse(http_config.public_root)
    webhook_url = urlparse.urlunsplit((
        root.scheme,
        root.netloc,
        posixpath.join(root.path, "harold/github"),
        None,
        None
    ))
    print "  Webhooks will be sent to %r" % webhook_url

    session = requests.session()
    session.auth = HTTPBasicAuth(access_token, "x-oauth-basic")
    session.verify = True
    session.headers["User-Agent"] = "Harold-by-@spladug"

    DESIRED_EVENTS = sorted(["push", "pull_request", "issue_comment", "pull_request_review"])
    for repo in sorted(repositories):
        print "  %s" % repo

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

            if get_netloc(old_url) == get_netloc(webhook_url):
                if old_url != webhook_url:
                    print "    Deleting hook with out of date URL %s" % hook["config"]["url"]
                    delete_hook = True
                elif sorted(hook["events"]) != DESIRED_EVENTS:
                    print "    Deleting hook with incorrect events (%s)" % (sorted(hook["events"]),)
                    delete_hook = True
                elif found_valid_hook:
                    print "    Deleting duplicate hook %d" % hook["id"]
                    delete_hook = True
                else:
                    print "    Found existing valid hook (%d)" % hook["id"]
                    found_valid_hook = True
            else:
                    print "    Skipping unrecognized hook %d" % hook["id"]

            if not dry_run and delete_hook:
                response = session.delete(_make_hooks_url(repo, str(hook["id"])))
                response.raise_for_status()

        if found_valid_hook:
            continue

        print "    Registering hook"
        if dry_run:
            continue
        response = session.post(
            _make_hooks_url(repo),
            data=json.dumps(dict(
                name="web",
                config=dict(
                    url=webhook_url,
                    secret=http_config.hmac_secret,
                ),
                events=DESIRED_EVENTS,
                active=True,
            )),
        )
        response.raise_for_status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", default=False)
    args = parser.parse_args()

    if args.dry_run:
        print "Dry run mode! No changes will actually be made."
    else:
        print "Live fire mode! All changes will be committed to GitHub."
    print

    print "Please enter a GitHub personal access token (found at Settings >>"
    print "Applications on GitHub) with the admin:repo_hook scope authorized"
    token = getpass.getpass("Token: ").strip()

    for config_filename in sorted(glob.glob("/etc/harold.d/*.ini")):
        configure_webhooks_for_instance(token, config_filename, args.dry_run)


if __name__ == "__main__":
    main()
