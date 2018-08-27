import collections

from flask import render_template, request, g

from salon.app import app
from salon.models import db, PullRequest, ReviewState


@app.before_request
def get_username():
    okta_id = request.headers["Authenticated-User"]
    g.username = okta_id.partition("@")[0].lower().replace(".", "-")


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


@app.route("/")
@app.route("/user/<override_username>")
def salon(override_username=None):
    username = g.username
    if override_username:
        username = override_username.lower()

    to_review_query = (
        PullRequest.query
            .options(db.subqueryload(PullRequest.states))
            .filter(PullRequest.state == "open")
            .filter(db.func.lower(PullRequest.author) != username)
            .join(ReviewState)
            .filter(db.func.lower(ReviewState.user) == username)
            .order_by(db.desc(PullRequest.created))
    )
    to_review = collections.defaultdict(list)
    for pull_request in to_review_query:
        state = pull_request.current_states()[username]
        to_review[state].append(pull_request)

    my_pulls_query = (
        PullRequest.query
            .options(db.subqueryload(PullRequest.states))
            .filter(PullRequest.state == "open")
            .filter(db.func.lower(PullRequest.author) == username)
            .order_by(db.desc(PullRequest.created))
    )
    my_pulls = _categorize_by_states(my_pulls_query)

    return render_template(
        "home.html",
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
