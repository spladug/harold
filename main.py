from twisted.internet import reactor, ssl

from irc import CommitNotificationFactory 
from http import make_site 
from conf import HaroldConfiguration

# read the config
config = HaroldConfiguration("harold.ini")

# set up the backend
irc_factory = CommitNotificationFactory(config)
listener = make_site(config, irc_factory)

# connect to IRC
if config.irc.use_ssl:
    context_factory = ssl.ClientContextFactory()
    reactor.connectSSL(config.irc.host, 
                       config.irc.port, 
                       irc_factory, 
                       context_factory) 
else:
    reactor.connectTCP(config.irc.host, config.irc.port, irc_factory) 

# listen for HTTP connections
reactor.listenTCP(config.http.port, listener)

# go
reactor.run()
