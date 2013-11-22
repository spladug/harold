import os

from flask import Flask

from harold.conf import HaroldConfiguration
from harold.plugins.database import DatabaseConfig
from harold.plugins.github import GitHubConfig


app = Flask(__name__)

# get the config
config = HaroldConfiguration(os.environ["HAROLD_CONFIG"])
_db_config = DatabaseConfig(config)
app.config["SQLALCHEMY_DATABASE_URI"] = _db_config.connection_string

_gh_config = GitHubConfig(config)
app.config["GITHUB_USERNAMES_BY_NICK"] = {v: k for k, v in
                                          _gh_config.nicks_by_user.iteritems()}


# register views
import salon.views
