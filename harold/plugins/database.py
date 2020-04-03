from baseplate import config
from sqlalchemy.engine import url
from twisted.enterprise.adbapi import ConnectionPool


class DatabasePlugin(ConnectionPool):
    """A plugin that provides a simple twisted ADBAPI interface to a DB."""

    def __init__(self, db_config):
        self.module = db_config.connection_string.get_dialect().dbapi()
        kwargs = db_config.connection_string.translate_connect_args()
        ConnectionPool.__init__(self, self.module.__name__, **kwargs)


def make_plugin(app_config):
    db_config = config.parse_config(app_config, {
        "connection_string": url.make_url,
    })
    return DatabasePlugin(db_config)
