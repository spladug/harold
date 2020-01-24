# -*- coding: utf-8 -*-

import collections
import datetime
import difflib
import json
import re

from baseplate.file_watcher import FileWatcher
from flask import render_template, request, g
from sqlalchemy import func

from salon.app import app
from salon.metrics import load_metrics
from salon.models import db, PullRequest, EmailAddress, Event


EMAIL_SANITY_CHECK_RE = re.compile(r"(^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$)")


@app.before_request
def get_username():
    okta_id = request.headers["Authenticated-User"].lower()

    if not EMAIL_SANITY_CHECK_RE.match(okta_id):
        return render_template("bad-email.html")

    email_address = EmailAddress.query.get(okta_id)
    if not email_address:
        email_address = EmailAddress(email_address=okta_id)
        db.session.add(email_address)
        db.session.commit()

    g.username = email_address.github_username


@app.context_processor
def inject_descriptions():
    return {
        "state_meanings": {
            "fish": "ready to merge",
            "haircut": "awaiting further review",
            "nail_care": "awaiting changes",
            "unreviewed": "not reviewed yet",
            "running": "unable to review",
            "eyeglasses": "awaiting reviewer summoning",
        },

        "emoji": {
            "fish": u"🐟",
            "haircut": u"💇",
            "nail_care": u"💅",
            "unreviewed": u"🙈",
            "eyeglasses": u"👓",
            "running": u"🏃",
            "no_bell": u"🔕",
        },

        "review_deadline": 1,
        "merge_deadline": 28,
    }


TIME_UNITS = [
    ("d", 24 * 60 * 60),
    ("h", 60 * 60),
    ("m", 60),
    ("s", 1),
]


@app.template_filter()
def timespan(seconds):
    parts = []
    for suffix, divisor in TIME_UNITS:
        unit, seconds = divmod(seconds, divisor)
        if unit:
            parts.append("%d%s" % (unit, suffix))
    return "".join(parts[:2])


@app.route("/")
@app.route("/user/<override_username>")
def salon(override_username=None):
    username = g.username
    if override_username:
        username = override_username.lower()

    to_review = collections.defaultdict(list)
    for pull_request in PullRequest.by_requested_reviewer(username):
        state = pull_request.state_for_user(username)
        to_review[state.state].append(pull_request)

    my_pulls = collections.defaultdict(list)
    for pull_request in PullRequest.by_author(username):
        stage = pull_request.review_stage()
        my_pulls[stage].append(pull_request)

    potential_spelling = None
    if override_username and not to_review and not my_pulls:
        all_authors = [row[0] for row in db.session.query(func.distinct(PullRequest.author))]
        if override_username not in all_authors:
            potential_spelling = difflib.get_close_matches(override_username, all_authors, n=1, cutoff=0.6)

    metrics = load_metrics()

    return render_template(
        "home.html",
        username=username,
        username_overridden=bool(override_username),
        my_pulls=my_pulls,
        to_review=to_review,
        metrics=metrics["user"].get(username.lower(), {"counters": {}, "timers": {}}),
        potential_spelling=potential_spelling,
    )


@app.route("/overview")
def overview():
    query = (
        PullRequest.query
            .options(db.subqueryload(PullRequest.states))
            .filter(PullRequest.state == "open")
            .order_by(db.desc(PullRequest.created))
    )

    pull_requests = collections.defaultdict(list)
    for pull_request in query:
        stage = pull_request.review_stage()
        pull_requests[stage].append(pull_request)

    metrics = load_metrics()
    return render_template(
        "overview.html",
        pull_requests=pull_requests,
        metrics=metrics["repository"]["*"],
    )


@app.route("/repo/<path:repo_name>")
def repo(repo_name):
    pull_requests = collections.defaultdict(list)
    for pull_request in PullRequest.by_repository(repo_name):
        stage = pull_request.review_stage()
        pull_requests[stage].append(pull_request)

    metrics = load_metrics()
    return render_template(
        "repo.html",
        repo_name=repo_name,
        pull_requests=pull_requests,
        metrics=metrics["repository"].get(repo_name.lower(), {"counters": {}, "timers": {}}),
    )


SALON_FILEWATCHER = FileWatcher("/var/lib/harold/salons.json", json.load)


@app.route("/salons")
def salons():
    return render_template(
        "salons.html",
        salons=SALON_FILEWATCHER.get_data(),
    )


@app.route("/emoji")
def emoji():
    return render_template("emoji.html")


@app.route("/stats")
def stats():
    limit = int(request.args.get("limit", "10"))

    metrics = load_metrics()

    by_repo = collections.defaultdict(lambda: collections.defaultdict(dict))
    for repo_name, metric_kinds in metrics["repository"].items():
        if repo_name == "*":
            continue

        for counter_name, counter_value in metric_kinds.get("counters", {}).items():
            by_repo["counters"][counter_name][repo_name] = counter_value

        for timer_name, timer_value in metric_kinds.get("timers", {}).items():
            by_repo["timers"][timer_name][repo_name] = timer_value

    by_user = collections.defaultdict(lambda: collections.defaultdict(dict))
    for user_name, metric_kinds in metrics["user"].items():
        if user_name == "*":
            continue

        for counter_name, counter_value in metric_kinds.get("counters", {}).items():
            by_user["counters"][counter_name][user_name] = counter_value

        for timer_name, timer_value in metric_kinds.get("timers", {}).items():
            by_user["timers"][timer_name][user_name] = timer_value

    return render_template(
        "stats.html",
        by_repo=by_repo,
        by_user=by_user,
        limit=limit,
    )


@app.route("/log")
def log():
    before = request.args.get("before")
    if before:
        try:
            before = datetime.datetime.strptime(before, "%Y-%m-%dT%H:%M:%S")
        except (TypeError, ValueError):
            before = None

    try:
        count = int(request.args.get("count"))
    except (TypeError, ValueError):
        count = 25
    count = min(count, 100)

    event_types = request.args.getlist("event_type")
    users = request.args.getlist("user")

    query = Event.query.order_by(db.desc(Event.timestamp))
    if before:
        query = query.filter(Event.timestamp <= before)
    if event_types:
        query = query.filter(Event.event.in_(event_types))
    if users:
        query = query.filter(Event.actor.in_(users))
    query = query.limit(count)

    return render_template(
        "log.html",
        events=list(query),
        before=before,
        count=count,
        event_types=event_types,
    )
