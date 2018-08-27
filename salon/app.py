import logging

from flask import Flask


app = Flask(__name__)


# load the rest of the config from the salon config file
# - flask sessions should be configured (at minimum SECRET_KEY should be set)
# - database url: SQLALCHEMY_DATABASE_URI
# - comma-delimited list of github orgs to allow access: GITHUB_ORGS
# - anything else flask allows to be configured
app.config.from_envvar("SALON_CONFIG")

# just output to console!
logging.basicConfig(level=logging.INFO)

# register views
import salon.views
