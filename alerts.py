from http import ProtectedResource
from conf import PluginConfig, Option, tup


class AlertsConfig(PluginConfig):
    recipients = Option(tup, default=[])


class BroadcastAlertListener(ProtectedResource):
    isLeaf = True

    def __init__(self, http, alerter):
        ProtectedResource.__init__(self, http)
        self.alerter = alerter

    def _handle_request(self, request):
        tag = request.args['tag'][0]
        message = request.args['message'][0]
        self.alerter.alert(tag, message)


class Alerter(object):
    def __init__(self, config, bot):
        self.config = config
        self.bot = bot

    def broadcast(self, message):
        for recipient in self.config.recipients:
            self.bot.sendMessage(recipient, message)

    def alert(self, tag, message):
        self.broadcast(message)

    def wall(self, bot, sender, *message):
        "Broadcast a message to all other alert-recipients."
        short_name = sender.split('@')[0]
        self.broadcast("<%s> %s" % (short_name, ' '.join(message)))


def make_plugin(config, http, jabber):
    alerts_config = AlertsConfig(config)
    alerter = Alerter(alerts_config, jabber.bot)

    # create the http resource
    http.root.putChild("alert", BroadcastAlertListener(http, alerter))

    # add the wall command
    jabber.register_command(alerter.wall)
