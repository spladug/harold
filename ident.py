from twisted.protocols.basic import LineReceiver
from twisted.application import internet
from twisted.internet.protocol import Factory

from plugin import Plugin
from conf import PluginConfig, Option

class IdentConfig(PluginConfig):
    user = Option(str, default="harold")
    port = Option(int, default=113)


class IdentProtocol(LineReceiver):
    def lineReceived(self, request):
        self.transport.write(request + ":USERID:UNIX:" + self.factory.user)
        self.transport.loseConnection()


def make_plugin(config):
    ident_config = IdentConfig(config)

    p = Plugin()
    factory = Factory()
    factory.protocol = IdentProtocol
    factory.user = ident_config.user

    p.add_service(internet.TCPServer(ident_config.port, factory))

    return p
