from twisted.words.xish import domish
from twisted.words.protocols.jabber import xmlstream, client, jid
from twisted.application import internet

from http import ProtectedResource


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

        body = str(message.body)
        print body
        self.sendMessage(message['from'], body)

    # methods
    def setAvailable(self):
        presence = domish.Element((None, 'presence'))
        self.send(presence)

    def sendMessage(self, to, content):
        message = domish.Element((None, 'message'))
        message['to'] = to
        message.addElement('body', content=content)
        self.send(message)

    def processAlert(self, tag, message):
        print "tag = %s; message = %s" % (tag, message)


def make_service(config, root):
    # set up the jabber bot
    id = jid.JID(config.jabber.id)
    factory = client.XMPPClientFactory(id, config.jabber.password)
    manager = xmlstream.StreamManager(factory)
    manager.logTraffic = True
    bot = JabberBot(config)
    bot.setHandlerParent(manager)

    # create the http resource
    root.putChild("alert", BroadcastAlertListener(config, bot))

    return internet.TCPClient(config.jabber.host,
                              config.jabber.port,
                              factory)
