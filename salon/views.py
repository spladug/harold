import base64
import collections
import functools
import os
import time

from flask import render_template, session, redirect, request, abort

from harold.plugins.http import constant_time_compare
from salon.app import app, github
from salon.models import db, PullRequest, ReviewState


def _or_list(items):
    if len(items) == 1:
        return items[0]
    return ", ".join(items[:-1]) + " or " + items[-1]


@app.before_request
def csrf_protect():
    if request.method == "POST":
        expected = session.pop("_csrf_token", None)
        actual = request.form.get("_csrf_token")

        if not (expected and constant_time_compare(expected, actual)):
            abort(400)


def make_csrf_token():
    if "_csrf_token" not in session:
        session["_csrf_token"] = base64.b64encode(os.urandom(16))
    return session["_csrf_token"]


app.jinja_env.globals["csrf_token"] = make_csrf_token


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
    }


def _categorize_by_states(query):
    pull_requests = collections.defaultdict(list)
    for pull_request in query:
        states_by_reviewer = pull_request.current_states()

        # no states at all is a completely separate issue
        if not any(reviewer != pull_request.author
                   for reviewer in states_by_reviewer):
            pull_requests["eyeglasses"].append(pull_request)
            continue

        # now, take away the "nope" people and see what's up
        states = states_by_reviewer.values()
        states = [state for state in states
                  if state not in ("unreviewed", "running")]
        if not states:
            verdict = "unreviewed"
        elif all(state == "fish" for state in states):
            verdict = "fish"
        elif any(state == "nail_care" for state in states):
            verdict = "nail_care"
        else:
            verdict = "haircut"
        pull_requests[verdict].append(pull_request)
    return pull_requests


@app.route("/login")
def login():
    if session.get("username"):
        return redirect("/")

    return render_template(
        "login-required.html",
        organization=_or_list(app.config["GITHUB_ORGS"]),
    )


@app.route("/login", methods=["POST"])
def post_login():
    if session.get("username"):
        return "already logged in", 403
    return github.authorize("read:org")


@app.route("/logout")
def logout():
    if not session.get("username"):
        return redirect("/")
    return render_template("logout.html")


@app.route("/logout", methods=["POST"])
def post_logout():
    if not session.get("username"):
        return "you must be logged in to log out", 403

    del session["username"]
    del session["timestamp"]
    return redirect("/")


@app.route("/github-callback")
@github.authorized_handler
def authorized(oauth_token):
    if not oauth_token:
        return render_template("login-failed.html", reason="not authorized")

    github.access_token_getter(lambda: oauth_token)

    userinfo = github.get("user")
    username = userinfo["login"]

    orgs = github.get("user/orgs")
    for org in orgs:
        if org["login"] in app.config["GITHUB_ORGS"]:
            break
    else:
        reason = "@{username} is not a member of {org}".format(
            username=username, org=_or_list(app.config["GITHUB_ORGS"]))
        return render_template("login-failed.html", reason=reason)

    session["username"] = username
    session["timestamp"] = int(time.time())
    return redirect("/")


def authentication_required(fn):
    @functools.wraps(fn)
    def authenticator(*args, **kwargs):
        github_username = session.get("username")

        if not github_username:
            return redirect("/login")

        timestamp = session.get("timestamp") or 0
        session_age = time.time() - timestamp
        if session_age >= app.config["MAX_SESSION_AGE"].total_seconds():
            del session["username"]
            del session["timestamp"]
            return redirect("/login")

        return fn(github_username.lower(), *args, **kwargs)
    return authenticator


@app.route("/")
@app.route("/user/<override_username>")
@authentication_required
def salon(github_username, override_username=None):
    if override_username:
        github_username = override_username.lower()

    to_review_query = (
        PullRequest.query
            .options(db.subqueryload(PullRequest.states))
            .filter(PullRequest.state == "open")
            .filter(db.func.lower(PullRequest.author) != github_username)
            .join(ReviewState)
            .filter(db.func.lower(ReviewState.user) == github_username)
            .order_by(db.desc(PullRequest.created))
    )
    to_review = collections.defaultdict(list)
    for pull_request in to_review_query:
        state = pull_request.current_states()[github_username]
        to_review[state].append(pull_request)

    my_pulls_query = (
        PullRequest.query
            .options(db.subqueryload(PullRequest.states))
            .filter(PullRequest.state == "open")
            .filter(db.func.lower(PullRequest.author) == github_username)
            .order_by(db.desc(PullRequest.created))
    )
    my_pulls = _categorize_by_states(my_pulls_query)

    return render_template(
        "home.html",
        github_username=github_username,
        my_pulls=my_pulls,
        to_review=to_review,
    )


@app.route("/overview")
@authentication_required
def overview(github_username):
    query = (
        PullRequest.query
            .options(db.subqueryload(PullRequest.states))
            .filter(PullRequest.state == "open")
            .order_by(db.desc(PullRequest.created))
    )
    pull_requests = _categorize_by_states(query)

    return render_template(
        "overview.html",
        pull_requests=pull_requests,
        github_username=github_username,
    )
