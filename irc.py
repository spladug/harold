#!/usr/bin/python

from twisted.words.protocols import irc
from twisted.internet import protocol, ssl
from twisted.application import internet
from twisted.web import resource

from dispatcher import Dispatcher
from http import ProtectedResource
from postreceive import PostReceiveDispatcher


def git_commit_id():
    from subprocess import Popen, PIPE

    try:
        result = Popen(["git", "rev-parse", "HEAD"], stdout=PIPE)
        return result.communicate()[0][:8]
    except:
        return ""


class IRCBot(irc.IRCClient):
    realname = "Harold (%s)" % git_commit_id()
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


class _PostReceiveListener(ProtectedResource):
    isLeaf = True

    def __init__(self, config, dispatcher):
        ProtectedResource.__init__(self, config)
        self.dispatcher = PostReceiveDispatcher(config, dispatcher)

    def _handle_request(self, request):
        post_data = request.args['payload'][0]
        self.dispatcher.dispatch(post_data)


class _MessageListener(ProtectedResource):
    isLeaf = True

    def __init__(self, config, dispatcher):
        ProtectedResource.__init__(self, config)
        self.dispatcher = dispatcher

    def _handle_request(self, request):
        channel = request.args['channel'][0]
        message = request.args['message'][0]
        self.dispatcher.send_message(channel, message)


class _SetTopicListener(ProtectedResource):
    isLeaf = True

    def __init__(self, config, dispatcher):
        ProtectedResource.__init__(self, config)
        self.dispatcher = dispatcher

    def _handle_request(self, request):
        channel = request.args['channel'][0]
        new_topic = request.args['topic'][0]
        self.dispatcher.set_topic(channel, new_topic)


class _RestoreTopicListener(ProtectedResource):
    isLeaf = True

    def __init__(self, config, dispatcher):
        ProtectedResource.__init__(self, config)
        self.dispatcher = dispatcher

    def _handle_request(self, request):
        channel = request.args['channel'][0]
        self.dispatcher.restore_topic(channel)


def make_service(config, root):
    dispatcher = Dispatcher()

    # add the http resources
    root.putChild('post-receive', _PostReceiveListener(config, dispatcher))
    root.putChild('message', _MessageListener(config, dispatcher))

    topic_root = resource.Resource()
    root.putChild('topic', topic_root)
    topic_root.putChild('set', _SetTopicListener(config, dispatcher))
    topic_root.putChild('restore', _RestoreTopicListener(config, dispatcher))

    # set up the IRC client
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
