import collections

from flask import render_template, abort, request, g

from salon import app
from salon.models import db, PullRequest, ReviewState


def _extract_cn_from_dn(dn):
    """Given a distinguished name, returns the common name attribute."""
    # this is so ugly i love it. i'm not changing it. go away. <3
    return dict(attr.partition("=")[::2] for attr in dn.split("/")).get("CN")


def internal_to_github(username):
    return app.config["GITHUB_USERNAMES_BY_NICK"].get(username, username)


@app.before_request
def check_certificate():
    if request.headers.get("X-Client-Verified", "FAILED") != "SUCCESS":
        abort(400)

    common_name = _extract_cn_from_dn(request.headers["X-Client-DN"])
    if not common_name:
        abort(400)

    g.username = common_name


@app.context_processor
def inject_descriptions():
    return {
        "state_meanings": {
            "fish": "ready to merge",
            "haircut": "awaiting further review",
            "nail_care": "awaiting fixes",
            "unreviewed": "not reviewed yet",
            "eyeglasses": "awaiting reviewer summoning",
        },
    }


@app.route("/")
def salon():
    github_username = internal_to_github(g.username).lower()

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
    my_pulls = collections.defaultdict(list)
    for pull_request in my_pulls_query:
        states = pull_request.current_states().values()

        # no states at all is a completely separate issue
        if not states:
            my_pulls["eyeglasses"].append(pull_request)
            continue

        # now, take away the "haven't looked yet" people and see what's up
        states = [state for state in states if state != "unreviewed"]
        if not states:
            verdict = "unreviewed"
        elif all(state == "fish" for state in states):
            verdict = "fish"
        elif any(state == "nail_care" for state in states):
            verdict = "nail_care"
        else:
            verdict = "haircut"
        my_pulls[verdict].append(pull_request)

    return render_template(
        "home.html",
        github_username=github_username,
        internal_username=g.username,
        my_pulls=my_pulls,
        to_review=to_review,
    )
