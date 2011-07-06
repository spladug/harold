#!/usr/bin/python

from twisted.words.protocols import irc
from twisted.internet import protocol, ssl
from twisted.application import internet


class IRCBot(irc.IRCClient):
    lineRate = 1  # rate limit to 1 message / second

    def signedOn(self):
        self.topics = {}
        self.topic_i_just_set = None

        for channel in self.factory.config.channels:
            self.join(channel)

        self.factory.dispatcher.registerConsumer(self)

    def topicUpdated(self, user, channel, topic):
        if topic != self.topic_i_just_set:
            self.topics[channel] = topic

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self)
        self.factory.dispatcher.deregisterConsumer(self)

    def privmsg(self, user, channel, msg):
        if not msg.startswith(self.nickname):
            return

        self.me(channel, "is a bot written by spladug.")

    def send_message(self, channel, message):
        self.msg(channel, message.encode('utf-8'))

    def set_topic(self, channel, topic):
        self.topic_i_just_set = topic
        self.send_message("ChanServ", " ".join(("TOPIC", channel, topic)))

    def restore_topic(self, channel):
        self.set_topic(channel, self.topics[channel])


class IRCBotFactory(protocol.ClientFactory):
    def __init__(self, config, dispatcher):
        self.config = config
        self.dispatcher = dispatcher

        class _ConfiguredBot(IRCBot):
            nickname = self.config.irc.nick
            password = self.config.irc.password
        self.protocol = _ConfiguredBot

    def clientConnectionLost(self, connector, reason):
        connector.connect()


def make_service(config, dispatcher):
    irc_factory = IRCBotFactory(config, dispatcher)

    if config.irc.use_ssl:
        context_factory = ssl.ClientContextFactory()
        return internet.SSLClient(config.irc.host,
                                  config.irc.port,
                                  irc_factory,
                                  context_factory)
    else:
        return internet.TCPClient(config.irc.host,
                                  config.irc.port,
                                  irc_factory)
