from twisted.internet import reactor
from twisted.web import server

from irc import CommitNotificationFactory 
from http import PostReceiveNotifier

irc_factory = CommitNotificationFactory("#spladug")
listener = server.Site(PostReceiveNotifier(irc_factory))
#reactor.connectSSL("chat.freenode.net", 7000, irc_factory) 
reactor.connectTCP("chat.freenode.net", 6667, irc_factory) 
reactor.listenTCP(8888, listener)
reactor.run()
