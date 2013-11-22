from sqlalchemy.engine import url
from twisted.enterprise.adbapi import ConnectionPool

from harold.conf import PluginConfig, Option
from harold.plugin import Plugin


class DatabaseConfig(PluginConfig):
    connection_string = Option(str)

    def get_module_and_params(self):
        """Parse the SQLAlchemy connection string and return DBAPI info."""
        sa_url = url.make_url(self.connection_string)
        dialect_cls = sa_url.get_dialect()
        return dialect_cls.dbapi(), sa_url.translate_connect_args()


class DatabasePlugin(ConnectionPool, Plugin):
    """A plugin that provides a simple twisted ADBAPI interface to a DB."""

    def __init__(self, db_config):
        Plugin.__init__(self)
        self.module, kwargs = db_config.get_module_and_params()
        ConnectionPool.__init__(self, self.module.__name__, **kwargs)


def make_plugin(config):
    db_config = DatabaseConfig(config)
    return DatabasePlugin(db_config)
