from http import ProtectedResource
from plugin import Plugin
from conf import PluginConfig, Option, tup


class AlertsConfig(PluginConfig):
    recipients = Option(tup, default=[])


class BroadcastAlertListener(ProtectedResource):
    isLeaf = True

    def __init__(self, config, http, bot):
        ProtectedResource.__init__(self, http)
        self.bot = bot
        self.config = config

    def _broadcast(self, message):
        for recipient in self.config.recipients:
            self.bot.sendMessage(recipient, message)

    def _handle_request(self, request):
        #tag = request.args['tag'][0]
        message = request.args['message'][0]
        self._broadcast(message)

    def wall(self, jabberbot, sender, *message):
        "Broadcast a message to all other alert-recipients."
        short_name = sender.split('@')[0]
        self._broadcast("<%s> %s" % (short_name, ' '.join(message)))


def make_plugin(config, http, jabber):
    p = Plugin()
    alerts_config = AlertsConfig(config)

    # create the http resource
    alerter = BroadcastAlertListener(alerts_config,
                                     http,
                                     jabber.bot)
    http.root.putChild("alert", alerter)

    # add the wall command
    jabber.register_command(alerter.wall)

    return p
