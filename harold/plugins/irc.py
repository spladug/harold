#!/usr/bin/python

import os
import traceback

from twisted.words.protocols import irc
from twisted.internet import protocol, ssl
from twisted.application import internet

from harold.dispatcher import Dispatcher
from harold.handlers import Handlers, NoHandlerError
from harold.plugin import Plugin
from harold.conf import PluginConfig, Option


class IrcConfig(PluginConfig):
    username = Option(str, default=None)
    nick = Option(str)
    password = Option(str, default=None)
    host = Option(str)
    port = Option(int, default=6667)
    use_ssl = Option(bool, default=False)
    userserv_password = Option(str, default=None)


def who(irc, sender, channel, *args):
    irc.describe(channel, "is a bot. see https://github.com/spladug/harold")


def debug(irc, sender, channel, *args):
    instance_name = os.environ.get("name", "main")
    if not args or args[0] == instance_name:
        irc.describe(channel, "instance `%s` is up!" % os.environ.get("name", "main"))


class IRCBot(irc.IRCClient):
    realname = "Harold"
    lineRate = 1  # rate limit to 1 message / second
    heartbeatInterval = 30
    maxOutstandingHeartbeats = 3

    def irc_PONG(self, prefix, params):
        print "Received PONG."
        self.outstanding_heartbeats = max(self.outstanding_heartbeats-1, 0)

    def startHeartbeat(self):
        self.outstanding_heartbeats = 0
        irc.IRCClient.startHeartbeat(self)

    def _sendHeartbeat(self):
        if self.outstanding_heartbeats > self.maxOutstandingHeartbeats :
            print "Too many heartbeats missed. Killing connection."
            self.transport.loseConnection()
            return
        else:
            print "Sending PING. %d heartbeats outstanding." % self.outstanding_heartbeats

        irc.IRCClient._sendHeartbeat(self)
        self.outstanding_heartbeats += 1

    def signedOn(self):
        print "Signed on!"

        if self.userserv_password:
            self.msg("userserv", "login %s %s" % (self.username,
                                                  self.userserv_password))

        self.factory.dispatcher.registerConsumer(self)

    def connectionLost(self, *args, **kwargs):
        print "Connection lost."
        irc.IRCClient.connectionLost(self, *args, **kwargs)
        self.factory.dispatcher.deregisterConsumer(self)

    def privmsg(self, user, channel, msg):
        sender_nick = user.partition('!')[0]
        self.factory.onMessageReceived(sender_nick, channel, msg)

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
        self.topic(channel, topic.encode('utf-8'))



class IRCBotFactory(protocol.ClientFactory):
    protocol = IRCBot

    def __init__(self, plugin, config, dispatcher):
        self.plugin = plugin
        self.config = config
        self.dispatcher = dispatcher

    def buildProtocol(self, addr):
        prot = protocol.ClientFactory.buildProtocol(self, addr)
        prot.nickname = self.config.nick
        prot.password = self.config.password
        prot.username = self.config.username
        prot.userserv_password = self.config.userserv_password
        return prot

    def clientConnectionFailed(self, connector, reason):
        connector.connect()

    def clientConnectionLost(self, connector, reason):
        connector.connect()

    def onMessageReceived(self, sender_nick, channel, msg):
        self.plugin.onMessageReceived(sender_nick, channel, msg)


class IrcPlugin(Plugin):
    def __init__(self):
        self._handlers = Handlers()
        super(IrcPlugin, self).__init__()

    def register_command(self, handler):
        self._handlers.register(handler.__name__, handler)

    def onMessageReceived(self, sender_nick, channel, msg):
        split = msg.split()
        if len(split) >= 2:
            highlight = split[0].lower()
        else:
            highlight = ""

        highlight = highlight.lstrip("@")

        if not highlight.startswith(self.config.nick):
            return

        command, args = (split[1].lower(), split[2:])

        try:
            self.handlers.process(command, self.bot, sender_nick, channel, *args)
        except NoHandlerError as exc:
            if exc.close_matches:
                self.bot.send_message(channel, "@%s: did you mean `%s`?" % (sender_nick, exc.close_matches[0]))
        except:
            traceback.print_exc()


def make_plugin(config, http=None):
    irc_config = IrcConfig(config)
    dispatcher = Dispatcher()

    # configure the default irc commands
    p = IrcPlugin()
    p.register_command(who)
    p.register_command(debug)

    # set up the IRC client
    irc_factory = IRCBotFactory(p, irc_config, dispatcher)
    p.bot = dispatcher
    if irc_config.use_ssl:
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
