from cStringIO import StringIO
from contextlib import contextmanager
import inspect

from twisted.words.xish import domish
from twisted.words.protocols.jabber import xmlstream, client, jid
from twisted.application import internet

from http import ProtectedResource


COMMANDS = {}
def command(fn):
    COMMANDS[fn.__name__] = fn
    return fn


class BroadcastAlertListener(ProtectedResource):
    isLeaf = True

    def __init__(self, config, bot):
        ProtectedResource.__init__(self, config)
        self.bot = bot

    def _handle_request(self, request):
        tag = request.args['tag'][0]
        message = request.args['message'][0]
        self.bot.processAlert(tag, message)


class JabberBot(xmlstream.XMPPHandler):
    def __init__(self, config):
        self.recipients = config.jabber.recipients
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

        if command not in COMMANDS:
            self.sendMessage(sender, ('Unknown command, "%s", try "help".'
                                      % command))
            return

        try:
            fn = COMMANDS[command]
            fn(self, sender, *args)
        except:
            self._detailed_help(sender, command=command, prefix="Usage:")

    # methods
    def setAvailable(self):
        presence = domish.Element((None, 'presence'))
        self.send(presence)

    def sendMessage(self, to, content):
        message = domish.Element((None, 'message'))
        message['to'] = to
        message.addElement('body', content=content)
        self.send(message)

    def broadcast(self, content):
        for recipient in self.recipients:
            self.sendMessage(recipient, content)

    def processAlert(self, tag, message):
        self.broadcast(message)

    def _detailed_help(self, sender, command, prefix=None):
        if command not in COMMANDS:
            self.sendMessage(sender, "Unknown command '%s'" % command)
            return

        fn = COMMANDS[command]
        args, varargs, keywords, defaults = inspect.getargspec(fn)
        offset_of_first_default = -len(defaults) if defaults else None

        with self.message(sender) as m:
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

    @contextmanager
    def message(self, to):
        io = StringIO()
        yield io
        self.sendMessage(to, io.getvalue())

    # im commands
    @command
    def help(self, sender, command=None):
        "Get information on available commands."
        if command:
            # send detailed documentation on the specified command
            self._detailed_help(sender, command)
        else:
            # send an overview of available commands
            with self.message(sender) as m:
                print >>m, "Available commands:"
                for command in COMMANDS.itervalues():
                    print >>m, "*%s* %s" % (command.__name__,
                                            command.__doc__.splitlines()[0])
                print >>m, ('Try "help <command>" to see more details ' +
                            'on a specific command')

    @command
    def wall(self, sender, *message):
        "Broadcast a message to all other alert-recipients."
        short_name = sender.split('@')[0]
        self.broadcast("<%s> %s" % (short_name, ' '.join(message)))


def make_service(config, root):
    # set up the jabber bot
    id = jid.JID(config.jabber.id)
    factory = client.XMPPClientFactory(id, config.jabber.password)
    manager = xmlstream.StreamManager(factory)
    bot = JabberBot(config)
    bot.setHandlerParent(manager)

    # create the http resource
    root.putChild("alert", BroadcastAlertListener(config, bot))

    return internet.TCPClient(config.jabber.host,
                              config.jabber.port,
                              factory)
