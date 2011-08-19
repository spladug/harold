from twisted.internet import reactor

from http import ProtectedResource
from conf import PluginConfig, Option, tup


class AlertsConfig(PluginConfig):
    recipients = Option(tup, default=[])
    refractory_period = Option(int, default=300)
    max_mute_duration = Option(int, default=3600)


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
        self.alerts = {}
        self.mutes = {}

    def broadcast(self, message):
        for recipient in self.config.recipients:
            self.bot.sendMessage(recipient, message)

    def alert(self, tag, message):
        if tag not in self.mutes:
            self.broadcast("<%s> %s" % (tag, message))
        self._register_alert(tag)

    def _register_alert(self, tag):
        if tag in self.alerts:
            self.alerts[tag].cancel()
        self.alerts[tag] = reactor.callLater(self.config.refractory_period,
                                             self._deregister_alert, tag)

    def _deregister_alert(self, tag):
        if tag in self.mutes:
            self.mutes[tag].cancel()
            self._deregister_mute(tag)
        del self.alerts[tag]

    def _register_mute(self, tag):
        self.mutes[tag] = reactor.callLater(self.config.max_mute_duration,
                                            self._deregister_mute, tag)

    def _deregister_mute(self, tag):
        del self.mutes[tag]

    def broadcast_from(self, sender, message):
        short_name = sender.split('@')[0]
        self.broadcast("<%s> %s" % (short_name, message))

    def wall(self, bot, sender, *message):
        "Broadcast a message to all other alert-recipients."
        self.broadcast_from(sender, ' '.join(message))

    def ack(self, bot, sender, tag):
        """Acknowledge an alert and silence this occurence of it.

        An occurence of the alert is defined as all instances of
        this alert until a period of time (default of 5 minutes)
        passes with no occurence of alerts with this tag.
        """
        if tag in self.mutes:
            self.bot.sendMessage(sender, "\"%s\" is already acknowledged."
                                         % tag)
        elif tag in self.alerts:
            self.broadcast_from(sender, "acknowledged %s" % tag)
            self._register_mute(tag)
        else:
            self.bot.sendMessage(sender,
                                 "No live alerts with tag \"%s\"." % tag)


def make_plugin(config, http, jabber):
    alerts_config = AlertsConfig(config)
    alerter = Alerter(alerts_config, jabber.bot)

    # create the http resource
    http.root.putChild("alert", BroadcastAlertListener(http, alerter))

    # add commands
    jabber.register_command(alerter.wall)
    jabber.register_command(alerter.ack)
