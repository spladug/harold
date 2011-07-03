from twisted.internet import reactor, ssl

from commitqueue import CommitQueue
from irc import CommitNotificationBotFactory 
from http import make_site 
from conf import HaroldConfiguration

config = HaroldConfiguration("harold.ini")
queue = CommitQueue()

# connect to IRC
irc_factory = CommitNotificationBotFactory(config, queue)
if config.irc.use_ssl:
    context_factory = ssl.ClientContextFactory()
    reactor.connectSSL(config.irc.host, 
                       config.irc.port, 
                       irc_factory, 
                       context_factory) 
else:
    reactor.connectTCP(config.irc.host, config.irc.port, irc_factory) 

# listen for HTTP connections
listener = make_site(config, queue)
reactor.listenTCP(config.http.port, listener)

# go
reactor.run()
