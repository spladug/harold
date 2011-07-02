#!/usr/bin/python

from collections import deque

from twisted.words.protocols import irc
#from twisted.python import log
from twisted.internet import reactor, protocol, task

class CommitNotificationBot(irc.IRCClient):
    def signedOn(self):
        for channel in self.factory.config.channels:
            self.join(channel)

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        self.factory.clientConnectionMade(self)

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self)
        self.factory.clientConnectionGone(self)

    def notify(self, notification):
        self.msg(self.factory.channel, notification)

class CommitNotificationFactory(protocol.ClientFactory):
    protocol = CommitNotificationBot

    def __init__(self, config):
        self.config = config 

        class _ConfiguredBot(CommitNotificationBot):
            nickname = self.config.irc.nick
            password = self.config.irc.password
        self.protocol = _ConfiguredBot

        self.clients = []
        self.queued_notifications = deque()
        self.task = task.LoopingCall(self._dispatch)

    def enqueue_notification(self, notification):
        if not len(self.queued_notifications):
            self.task.start(2.0, now=False)
        self.queued_notifications.append(notification)

    def _dispatch(self):
        if len(self.clients) != 1:
            return

        notification = self.queued_notifications.popleft()
        self.clients[0].notify(notification)

        if len(self.queued_notifications) == 0:
            self.task.stop()

    def clientConnectionMade(self, connection):
        self.clients.append(connection)

    def clientConnectionGone(self, connection):
        self.clients.remove(connection)

    def clientConnectionLost(self, connector, reason):
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        reactor.stop()
