#!/usr/bin/python

from twisted.words.protocols import irc
#from twisted.python import log
from twisted.internet import reactor, protocol

def messages_from_commit(repository, commit):
    info = {}

    info['repository'] = repository.name
    info['url'] = commit['short_url']
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

        self.factory.queue.registerConsumer(self)

    def connectionLost(self, reason):
        irc.IRCClient.connectionLost(self)
        self.factory.queue.deregisterConsumer(self)

    def privmsg(self, user, channel, msg):
        if not msg.startswith(self.nickname):
            return

        self.me(channel, 
                "is a bot written by spladug. It announces new GitHub commits.")

    def onNewCommit(self, repository, commit):
        for line in messages_from_commit(repository, commit):
            self.msg(repository.channel, line.encode("utf-8"))

class CommitNotificationBotFactory(protocol.ClientFactory):
    def __init__(self, config, queue):
        self.config = config 
        self.queue = queue

        class _ConfiguredBot(CommitNotificationBot):
            nickname = self.config.irc.nick
            password = self.config.irc.password
        self.protocol = _ConfiguredBot

    def clientConnectionLost(self, connector, reason):
        connector.connect()

    def clientConnectionFailed(self, connector, reason):
        reactor.stop()
