import collections

from flask import render_template, abort, request, g

from salon import app
from salon.models import db, PullRequest, ReviewState


def _extract_cn_from_dn(dn):
    """Given a distinguished name, returns the common name attribute."""
    # this is so ugly i love it. i'm not changing it. go away. <3
    return dict(attr.partition("=")[::2] for attr in dn.split("/")).get("CN")


def internal_to_github(username):
    return app.config["GITHUB_USERNAMES_BY_NICK"].get(username.lower(),
                                                      username)


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
    my_pulls = _categorize_by_states(my_pulls_query)

    return render_template(
        "home.html",
        github_username=github_username,
        internal_username=g.username,
        my_pulls=my_pulls,
        to_review=to_review,
    )


@app.route("/overview")
def overview():
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
    )
