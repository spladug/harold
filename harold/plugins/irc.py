#!/usr/bin/python

import string
import random
import traceback

from twisted.words.protocols import irc
from twisted.internet import protocol, ssl
from twisted.application import internet
from twisted.web import resource

from harold.dispatcher import Dispatcher
from harold.plugins.http import ProtectedResource
from harold.plugin import Plugin
from harold.conf import PluginConfig, Option, tup
from harold.utils import Event


class IrcConfig(PluginConfig):
    username = Option(str, default=None)
    nick = Option(str)
    password = Option(str, default=None)
    host = Option(str)
    port = Option(int, default=6667)
    use_ssl = Option(bool, default=False)
    channels = Option(tup, default=[])
    userserv_password = Option(str, default=None)
    parrot_channel = Option(str, default=None)


def git_commit_id():
    from subprocess import Popen, PIPE

    try:
        result = Popen(["git", "rev-parse", "HEAD"], stdout=PIPE)
        return result.communicate()[0][:8]
    except:
        return ""

REVISION = git_commit_id()


def version(irc, sender, channel):
    nick = sender.partition('!')[0]
    irc.send_message(channel, "%s, i am running git revision %s" % (nick,
                                                                    REVISION))


def who(irc, sender, channel, *args):
    irc.describe(channel, "is a bot. see https://github.com/spladug/harold")


def wanna(irc, sender, channel, *args):
    if args:
        clean = args[0].translate(string.maketrans("", ""), string.punctuation)
        if clean.lower() == "cracker":
            irc.describe(channel, "squawks: yes!")
        elif clean.lower() == "rram":
            irc.describe(channel, "purrs.")
        else:
            irc.describe(channel, "flies away in disgust")


class IRCBot(irc.IRCClient):
    realname = "Harold (%s)" % REVISION
    lineRate = .25  # rate limit to 4 messages / second

    def signedOn(self):
        if self.userserv_password:
            self.msg("userserv", "login %s %s" % (self.username,
                                                  self.userserv_password))

        self.topics = {}
        self.topic_i_just_set = None

        for channel in self.factory.channels:
            self.join(channel)

        self.factory.dispatcher.registerConsumer(self)

    def topicUpdated(self, user, channel, topic):
        if topic != self.topic_i_just_set:
            self.topics[channel] = topic
        self.factory.plugin.topicUpdated(user, channel, topic)

    def connectionLost(self, *args, **kwargs):
        irc.IRCClient.connectionLost(self, *args, **kwargs)
        self.factory.dispatcher.deregisterConsumer(self)

    def maybeParrotMessage(self, user, channel, msg):
        fate = random.random()
        if channel == self.parrot_channel and fate < .005:
            parrotized = ' '.join(msg.split(' ')[-2:]) + ". squawk!"
            self.msg(self.parrot_channel, parrotized)
        elif channel == self.parrot_channel and fate < .0025:
            self.msg(self.parrot_channel,
                     "HERMOCRATES! A friend of Socrates! Bwaaak!")

    def privmsg(self, user, channel, msg):
        split = msg.split()
        if len(split) >= 2:
            highlight = split[0].lower()
        else:
            highlight = ""

        if not highlight.startswith(self.nickname):
            self.maybeParrotMessage(user, channel, msg)
            return

        command, args = (split[1].lower(), split[2:])
        fn = self.plugin.commands.get(command)
        if not fn:
            return

        try:
            fn(self, user, channel, *args)
        except:
            traceback.print_exc()
            self.describe(channel, "just had a hiccup.")

    def send_message(self, channel, message):
        # get rid of any evil characters that might allow shenanigans
        message = unicode(message)
        message = message.translate({
            ord("\r"): None,
            ord("\n"): None,
        })

        # ensure the message isn't too long
        message = message[:500]

        self.msg(channel, message.encode('utf-8'))

    def set_topic(self, channel, topic):
        self.topic_i_just_set = topic
        self.topic(channel, topic)

    def restore_topic(self, channel):
        self.set_topic(channel, self.topics[channel])


class IRCBotFactory(protocol.ClientFactory):
    def __init__(self, plugin, config, dispatcher, channels):
        self.plugin = plugin
        self.config = config
        self.dispatcher = dispatcher
        self.channels = channels

        class _ConfiguredBot(IRCBot):
            nickname = self.config.nick
            password = self.config.password
            plugin = self.plugin
            username = self.config.username
            userserv_password = self.config.userserv_password
            parrot_channel = self.config.parrot_channel
        self.protocol = _ConfiguredBot

    def clientConnectionLost(self, connector, reason):
        connector.connect()


class MessageListener(ProtectedResource):
    isLeaf = True

    def __init__(self, http, dispatcher):
        ProtectedResource.__init__(self, http)
        self.dispatcher = dispatcher

    def _handle_request(self, request):
        channel = request.args['channel'][0]
        message = unicode(request.args['message'][0], 'utf-8')
        self.dispatcher.send_message(channel, message)


class SetTopicListener(ProtectedResource):
    isLeaf = True

    def __init__(self, http, dispatcher):
        ProtectedResource.__init__(self, http)
        self.dispatcher = dispatcher

    def _handle_request(self, request):
        channel = request.args['channel'][0]
        new_topic = unicode(request.args['topic'][0], 'utf-8')
        self.dispatcher.set_topic(channel, new_topic)


class RestoreTopicListener(ProtectedResource):
    isLeaf = True

    def __init__(self, http, dispatcher):
        ProtectedResource.__init__(self, http)
        self.dispatcher = dispatcher

    def _handle_request(self, request):
        channel = request.args['channel'][0]
        self.dispatcher.restore_topic(channel)


class ChannelManager(object):
    def __init__(self, basic_channels, bot):
        self.bot = bot
        self.channels = set(basic_channels)

    def add(self, channel):
        if channel not in self.channels:
            self.channels.add(channel)
            self.bot.join(channel)

    def __iter__(self):
        return self.channels.__iter__()


class IrcPlugin(Plugin):
    def __init__(self):
        self.commands = {}
        self.topicUpdated = Event()
        super(IrcPlugin, self).__init__()

    def register_command(self, handler):
        self.commands[handler.__name__] = handler


def make_plugin(config, http=None):
    irc_config = IrcConfig(config)
    dispatcher = Dispatcher()
    channel_manager = ChannelManager(irc_config.channels, dispatcher)

    # add the http resources
    if http:
        http.root.putChild('message', MessageListener(http, dispatcher))
        topic_root = resource.Resource()
        http.root.putChild('topic', topic_root)
        topic_root.putChild('set', SetTopicListener(http, dispatcher))
        topic_root.putChild('restore', RestoreTopicListener(http, dispatcher))

    # configure the default irc commands
    p = IrcPlugin()
    p.register_command(version)
    p.register_command(who)
    p.register_command(wanna)

    # set up the IRC client
    irc_factory = IRCBotFactory(p, irc_config, dispatcher, channel_manager)
    p.config = irc_config
    p.bot = dispatcher
    p.channels = channel_manager
    if irc_config:
        context_factory = ssl.ClientContextFactory()
        p.add_service(internet.SSLClient(irc_config.host,
                                         irc_config.port,
                                         irc_factory,
                                         context_factory))
    else:
        p.add_service(internet.TCPClient(irc_config.host,
                                         irc_config.port,
                                         irc_factory))
    return p
