import logging

from flask import Flask

import flask_github


app = Flask(__name__)


# load the rest of the config from the salon config file
# - flask sessions should be configured (at minimum SECRET_KEY should be set)
# - database url: SQLALCHEMY_DATABASE_URI
# - github oauth: GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET
# - session ttl: MAX_SESSION_AGE (in seconds)
# - comma-delimited list of github orgs to allow access: GITHUB_ORGS
# - anything else flask allows to be configured
app.config.from_envvar("SALON_CONFIG")

# set up flask_github
github = flask_github.GitHub(app)

# just output to console!
logging.basicConfig(level=logging.INFO)

# register views
import salon.views
