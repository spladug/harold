import logging
import os

from flask import Flask

from harold.conf import HaroldConfiguration
from harold.plugins.database import DatabaseConfig

import flask_github


app = Flask(__name__)


# get the config
config = HaroldConfiguration(os.environ["HAROLD_CONFIG"])
_db_config = DatabaseConfig(config)
app.config["SQLALCHEMY_DATABASE_URI"] = _db_config.connection_string

# load the rest of the config from the salon config file
# - flask sessions should be configured (at minimum SECRET_KEY should be set)
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
