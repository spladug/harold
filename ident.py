from twisted.protocols.basic import LineReceiver
from twisted.application import internet
from twisted.internet.protocol import Factory


class IdentProtocol(LineReceiver):
    def lineReceived(self, request):
        self.transport.write(request + ":USERID:UNIX:" + self.factory.user)
        self.transport.loseConnection()


def make_service(config, root):
    factory = Factory()
    factory.protocol = IdentProtocol
    factory.user = config.ident.user

    return internet.TCPServer(config.ident.port, factory)
