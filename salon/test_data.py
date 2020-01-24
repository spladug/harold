import datetime

from salon.app import app
from salon.models import db
from salon.models import Event
from salon.models import PullRequest
from salon.models import ReviewState


@app.cli.command()
def make_test_data():
    now = datetime.datetime.utcnow()
    reviewers = {"foo": "fish", "bar": "nail_care", "baz": "unreviewed"}

    if not PullRequest.query.get(("example/test", 1)):
        pr_time = now - datetime.timedelta(hours=3)
        db.session.add(PullRequest(
            repository="example/test",
            id=1,
            created=pr_time,
            author="example",
            state="open",
            title="This is an example pull request",
            url="https://github.com/example/test/pull/1",
        ))
        db.session.add(Event(
            actor="example",
            event="opened",
            timestamp=pr_time,
            repository="example/test",
            pull_request_id=1,
            info={},
        ))
        db.session.add(Event(
            actor="example",
            event="review_requested",
            timestamp=pr_time,
            repository="example/test",
            pull_request_id=1,
            info={"targets": list(reviewers)},
        ))
        db.session.commit()

    for name, state in reviewers.iteritems():
        if not ReviewState.query.get(("example/test", 1, name)):
            db.session.add(ReviewState(
                repository="example/test",
                pull_request_id=1,
                user=name,
                timestamp=now,
                state=state,
            ))
            db.session.add(Event(
                actor=name,
                event="review",
                timestamp=now,
                repository="example/test",
                pull_request_id=1,
                info={"state": state},
            ))
            db.session.commit()
