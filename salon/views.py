import collections

from flask import render_template, request, g

from salon.app import app
from salon.models import db, PullRequest, ReviewState, EmailAddress


@app.before_request
def get_username():
    okta_id = request.headers["Authenticated-User"].lower()

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
    }


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

    return render_template(
        "home.html",
        username=username,
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

    pull_requests = collections.defaultdict(list)
    for pull_request in query:
        stage = pull_request.review_stage()
        pull_requests[stage].append(pull_request)

    return render_template(
        "overview.html",
        pull_requests=pull_requests,
    )
