import collections

from flask_sqlalchemy import SQLAlchemy

from salon.app import app


db = SQLAlchemy(app)


CalculatedReviewState = collections.namedtuple("CalculatedReviewState", "pull_request state timestamp")


class PullRequest(db.Model):
    __tablename__ = "github_pull_requests"
    repository = db.Column(db.String, primary_key=True, nullable=False)
    id = db.Column(db.Integer, primary_key=True, nullable=False)
    created = db.Column(db.DateTime, nullable=False)
    author = db.Column(db.String, nullable=False)
    state = db.Column(db.String, nullable=False)
    title = db.Column(db.String)
    url = db.Column(db.String)

    states = db.relationship(
        lambda: ReviewState,
        order_by=lambda: ReviewState.timestamp.desc(),
        backref="pull_request",
    )

    def current_states(self):
        haircut_time = None
        states_by_user = collections.OrderedDict()
        for state in self.states:
            if state.state == "haircut":
                haircut_time = state.timestamp
                continue

            if haircut_time and state.state not in ("unreviewed", "running"):
                new_state = "haircut"
                timestamp = haircut_time
            else:
                new_state = state.state
                timestamp = state.timestamp

            states_by_user[state.user.lower()] = CalculatedReviewState(self, new_state, timestamp)
        return states_by_user

    def state_for_user(self, username):
        states = self.current_states()
        return states[username.lower()]

    def review_stage(self):
        states_by_reviewer = self.current_states()

        if not states_by_reviewer:
            return "eyeglasses"

        # now, take away the "nope" people and see what's up
        states = states_by_reviewer.values()
        states = [state.state for state in states
                  if state.state not in ("unreviewed", "running")]

        if not states:
            return "unreviewed"
        elif all(state == "fish" for state in states):
            return "fish"
        elif any(state == "nail_care" for state in states):
            return "nail_care"

        return "haircut"

    @classmethod
    def by_requested_reviewer(cls, username):
        return (cls.query
            .options(db.subqueryload(PullRequest.states))
            .filter(PullRequest.state == "open")
            .filter(db.func.lower(PullRequest.author) != username)
            .join(ReviewState)
            .filter(db.func.lower(ReviewState.user) == username)
            .order_by(db.asc(ReviewState.timestamp))
        )

    @classmethod
    def by_author(cls, username):
        return (
            PullRequest.query
                .options(db.subqueryload(PullRequest.states))
                .filter(PullRequest.state == "open")
                .filter(db.func.lower(PullRequest.author) == username)
                .order_by(db.asc(PullRequest.created))
        )


class ReviewState(db.Model):
    __tablename__ = "github_review_states"
    __table_args__ = (
        db.ForeignKeyConstraint(["repository", "pull_request_id"],
                                ["github_pull_requests.repository",
                                 "github_pull_requests.id"]),
    )

    repository = db.Column(db.String, primary_key=True, nullable=False)
    pull_request_id = db.Column(db.Integer, primary_key=True, nullable=False)
    user = db.Column(db.String, primary_key=True, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    state = db.Column(db.String, nullable=False)


class Salon(db.Model):
    __tablename__ = "salons"

    name = db.Column(db.String, primary_key=True, nullable=False)
    conch_emoji = db.Column(db.String, nullable=False)
    deploy_hours_start = db.Column(db.String, default=True)
    deploy_hours_end = db.Column(db.String, default=True)
    tz = db.Column(db.String, default=True)
    allow_deploys = db.Column(db.Boolean, default=True)


class Repository(db.Model):
    __tablename__ = "repositories"

    name = db.Column(db.String, primary_key=True, nullable=False)
    salon = db.Column(db.String, db.ForeignKey("salons.name"), nullable=False)
    format = db.Column(db.String)
    bundled_format = db.Column(db.String)
    branches = db.Column(db.String, default="master")


class User(db.Model):
    __tablename__ = "users"

    irc_nick = db.Column(db.String, primary_key=True)
    github_username = db.Column(db.String, nullable=False)


class EmailAddress(db.Model):
    __tablename__ = "emails"

    email_address = db.Column(db.String, primary_key=True)
    opted_into_nags = db.Column(db.Boolean, default=True)

    @property
    def github_username(self):
        return self.email_address.partition("@")[0].lower().replace(".", "-")


db.create_all()
