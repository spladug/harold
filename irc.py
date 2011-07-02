#!/usr/bin/python

from collections import deque

from twisted.words.protocols import irc
#from twisted.python import log
from twisted.internet import reactor, protocol, task

def messages_from_commit(repository, commit):
    info = {}
    print commit

    info['repository'] = repository.name
    info['url'] = ""
    info['commit_id'] = commit['id'][:7]
    info['author'] = commit['author']['name']
    if 'username' in commit['author']:
        info['author'] = commit['author']['username']
    info['summary'] = commit['message'].splitlines()[0]

    yield repository.format % info

class CommitNotificationBot(irc.IRCClient):
    lineRate = 1 # rate limit to 1 message / second

    def signedOn(self):
        for channel in self.factory.config.channels:
            self.join(channel)

    def connectionMade(self):
        irc.IRCClient.connectionMade(self)
        self.factory.clientConnectionMade(self)

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self)
        self.factory.clientConnectionGone(self)

    def privmsg(self, user, channel, msg):
        if not msg.startswith(self.nickname):
            return

        self.me(channel, 
                "is a bot written by spladug. I announce new GitHub commits.")

    def notify(self, repository, commit):
        for line in messages_from_commit(repository, commit):
            self.msg(repository.channel, line.encode("utf-8"))

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

    def enqueue_notification(self, repository, notification):
        if not len(self.queued_notifications):
            self.task.start(1.0, now=False)
        self.queued_notifications.append((repository, notification))

    def _dispatch(self):
        if len(self.clients) != 1:
            return

        notification = self.queued_notifications.popleft()
        self.clients[0].notify(*notification)

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
