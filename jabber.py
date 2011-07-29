from cStringIO import StringIO
from contextlib import contextmanager
import inspect

from twisted.words.xish import domish
from twisted.words.protocols.jabber import xmlstream, client, jid
from twisted.application import internet

from conf import PluginConfig, Option
from plugin import Plugin

class JabberConfig(PluginConfig):
    host = Option(str)
    port = Option(int, default=5222)
    id = Option(str)
    password = Option(str)


class JabberPlugin(Plugin):
    def __init__(self):
        self.commands = {}
        super(JabberPlugin, self).__init__()

    def register_command(self, handler):
        self.commands[handler.__name__] = handler


def _detailed_help(bot, sender, command, prefix=None):
    if command not in bot.plugin.commands:
        bot.sendMessage(sender, "Unknown command '%s'" % command)
        return

    fn = bot.plugin.commands[command]
    args, varargs, keywords, defaults = inspect.getargspec(fn)
    offset_of_first_default = -len(defaults) if defaults else None

    with bot.message(sender) as m:
        if prefix:
            print >>m, prefix
        print >>m, command + " ",
        for arg in args[2:offset_of_first_default]:
            print >>m, arg + " ",
        if defaults:
            for arg in args[offset_of_first_default:]:
                print >>m, "[" + arg + "] ",
        if varargs:
            print >>m, " [" + varargs + "...]",
        print >>m, ""
        print >>m, fn.__doc__


def help(bot, sender, command=None):
    "Get information on available commands."
    if command:
        # send detailed documentation on the specified command
        _detailed_help(bot, sender, command)
    else:
        # send an overview of available commands
        with bot.message(sender) as m:
            print >>m, "Available commands:"
            for command in bot.plugin.commands.itervalues():
                print >>m, "*%s* - %s" % (command.__name__,
                                          command.__doc__.splitlines()[0])
            print >>m, ('Try "help <command>" to see more details ' +
                        'on a specific command')


class JabberBot(xmlstream.XMPPHandler):
    def __init__(self, plugin):
        self.plugin = plugin
        super(JabberBot, self).__init__()

    # event handlers
    def connectionInitialized(self):
        self.xmlstream.addObserver("/message", self.onMessage)
        self.setAvailable()

    def onMessage(self, message):
        if message["type"] != "chat":
            return

        if not (hasattr(message, "body") and message.body):
            return

        sender = message["from"]
        body = str(message.body)
        split = body.split(' ')
        command, args = split[0].lower(), filter(None, split[1:])

        if command not in self.plugin.commands:
            self.sendMessage(sender, ('Unknown command, "%s", try "help".'
                                      % command))
            return

        try:
            fn = self.plugin.commands[command]
            fn(self, sender, *args)
        except:
            _detailed_help(self, sender, command=command, prefix="Usage:")

    # api
    def setAvailable(self):
        presence = domish.Element((None, 'presence'))
        self.send(presence)

    def sendMessage(self, to, content):
        message = domish.Element((None, 'message'))
        message['to'] = to
        message.addElement('body', content=content)
        self.send(message)

    @contextmanager
    def message(self, to):
        io = StringIO()
        yield io
        self.sendMessage(to, io.getvalue())


def make_plugin(config):
    p = JabberPlugin()
    jabber_config = JabberConfig(config)

    # set up the jabber bot
    id = jid.JID(jabber_config.id)
    factory = client.XMPPClientFactory(id, jabber_config.password)
    manager = xmlstream.StreamManager(factory)
    bot = JabberBot(p)
    bot.setHandlerParent(manager)
    p.bot = bot

    p.add_service(internet.TCPClient(jabber_config.host,
                                     jabber_config.port,
                                     factory))

    # add the built-in commands
    p.register_command(help)

    return p

