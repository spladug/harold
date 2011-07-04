from twisted.internet import reactor, ssl

from dispatcher import Dispatcher
from irc import IRCBotFactory
from http import make_site
from conf import HaroldConfiguration

config = HaroldConfiguration("harold.ini")
dispatcher = Dispatcher()

# connect to IRC
irc_factory = IRCBotFactory(config, dispatcher)
if config.irc.use_ssl:
    context_factory = ssl.ClientContextFactory()
    reactor.connectSSL(config.irc.host,
                       config.irc.port,
                       irc_factory,
                       context_factory)
else:
    reactor.connectTCP(config.irc.host, config.irc.port, irc_factory)

# listen for HTTP connections
listener = make_site(config, dispatcher)
reactor.listenTCP(config.http.port, listener)

# go
reactor.run()
