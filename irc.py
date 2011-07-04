#!/usr/bin/python

from twisted.words.protocols import irc
#from twisted.python import log
from twisted.internet import reactor, protocol


class IRCBot(irc.IRCClient):
    lineRate = 1 # rate limit to 1 message / second

    def signedOn(self):
        for channel in self.factory.config.channels:
            self.join(channel)

        self.factory.queue.registerConsumer(self)

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self)
        self.factory.queue.deregisterConsumer(self)

    def privmsg(self, user, channel, msg):
        if not msg.startswith(self.nickname):
            return

        self.me(channel, 
                "is a bot written by spladug. It announces new GitHub commits.")

    def send_message(self, channel, message):
        self.msg(channel, message.encode('utf-8'))

class IRCBotFactory(protocol.ClientFactory):
    def __init__(self, config, queue):
        self.config = config 
        self.queue = queue

        class _ConfiguredBot(IRCBot):
            nickname = self.config.irc.nick
            password = self.config.irc.password
        self.protocol = _ConfiguredBot

    def clientConnectionLost(self, connector, reason):
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        reactor.stop()
