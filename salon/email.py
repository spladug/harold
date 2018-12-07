import collections
import datetime

from flask import render_template
from flask_mail import Mail, Message

from salon.app import app
from salon.models import db, PullRequest, ReviewState, EmailAddress


AgeBucket = collections.namedtuple("AgeBucket", "threshold name")


AGE_BUCKETS = (
    AgeBucket(datetime.timedelta(days=365), "year"),
    AgeBucket(datetime.timedelta(days=90), "quarter"),
    AgeBucket(datetime.timedelta(days=30), "month"),
    AgeBucket(datetime.timedelta(weeks=1), "week"),
    AgeBucket(datetime.timedelta(hours=24), "day"),
    AgeBucket(datetime.timedelta(seconds=0), "recent"),
)


@app.template_filter()
def bucket_by_age(items):
    now = datetime.datetime.now()
    by_bucket = collections.defaultdict(list)

    for item in items:
        try:
            timestamp = item.timestamp
        except AttributeError:
            timestamp = item.created

        age = now - timestamp

        for bucket in AGE_BUCKETS:
            if age > bucket.threshold:
                by_bucket[bucket.name].append(item)
                break

    for bucket in AGE_BUCKETS:
        yield bucket.name, by_bucket[bucket.name]


@app.template_filter()
def maybe_plural(count, word):
    if count == 1:
        return "%d %s" % (count, word)
    else:
        return "%d %ss" % (count, word)


@app.cli.command()
def send_naggy_emails():
    mail = Mail(app)

    with mail.connect() as conn:
        for email in EmailAddress.query.all():
            if email.opted_into_nags:
                send_naggy_email(conn, email.email_address, email.github_username)


def send_naggy_email(mail, email_address, github_username):
    print("Processing @%s" % github_username)

    to_review = []
    for pull_request in PullRequest.by_requested_reviewer(github_username):
        my_state = pull_request.state_for_user(github_username)
        if my_state.state not in ("haircut", "unreviewed"):
            continue
        to_review.append(my_state)

    my_pulls = []
    for pull_request in PullRequest.by_author(github_username):
        review_stage = pull_request.review_stage()
        if review_stage not in ("fish", "eyeglasses", "nail_care"):
            continue
        my_pulls.append(pull_request)

    if not to_review and not my_pulls:
        return

    print("- Sending nag to %r" % email_address)
    date = datetime.date.today().strftime("%b %d")

    message = Message()
    message.sender = u"Harold \U0001F487 <noreply@harold.snooguts.net>"
    message.subject = u"Outstanding pull requests for %s" % (date,)
    message.html = render_template(
        "email.html",
        username=github_username,
        to_review=to_review,
        my_pulls=my_pulls,
    )
    message.add_recipient(email_address)
    mail.send(message)
