import datetime
import functools
from email.mime.text import MIMEText

from twisted.internet import reactor

from http import ProtectedResource
from conf import PluginConfig, Option, tup
from utils import pretty_time_span
import watchdog


def make_short_name(jid):
    short_name = jid.split('@')[0]
    return short_name


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


class Alert(object):
    pass


class Alerter(object):
    def __init__(self, config, jabber_bot, smtp):
        self.config = config
        self.alerts = {}

        self.jabber_bot = jabber_bot
        self.smtp = smtp

        senders = {
            'smtp': self._send_smtp,
            'jabber': self._send_jabber,
        }
        self.recipients = []
        for recipient in self.config.recipients:
            medium, id = recipient.split(':', 1)
            sender = functools.partial(senders[medium], id)
            self.recipients.append(sender)

    def _send_smtp(self, recipient, message):
        email = MIMEText(message)
        self.smtp.sendmail(
            self.smtp.username,
            [recipient],
            email
        )

    def _send_jabber(self, recipient, message):
        self.jabber_bot.sendMessage(recipient, message)

    def broadcast(self, message):
        for recipient in self.recipients:
            recipient(message)

    def alert(self, tag, message):
        alert = self._register_alert(tag)
        if not alert.muted:
            self.broadcast("<%s> %s" % (tag, message))

    def _register_alert(self, tag):
        alert = self.alerts.get(tag)

        if not alert:
            alert = Alert()
            alert.first_seen = datetime.datetime.now()
            alert.count = 0
            alert.muted = False
            alert.expirator = None
            self.alerts[tag] = alert

        if alert.expirator:
            alert.expirator.cancel()

        alert.count += 1
        alert.last_seen = datetime.datetime.now()
        alert.expirator = reactor.callLater(
            self.config.refractory_period,
            self._deregister_alert,
            tag
        )
        return alert

    def _deregister_alert(self, tag):
        alert = self.alerts[tag]
        if alert.muted:
            alert.mute_expirator.cancel()
        del self.alerts[tag]

    def _register_mute(self, tag, sender):
        alert = self.alerts[tag]
        alert.muted = make_short_name(sender)
        alert.mute_expirator = reactor.callLater(
            self.config.max_mute_duration,
            self._deregister_mute,
            tag
        )

    def _deregister_mute(self, tag):
        alert = self.alerts[tag]
        alert.muted = False

    def broadcast_from(self, sender, message):
        short_name = make_short_name(sender)
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
        alert = self.alerts.get(tag)

        if not alert:
            matching_tags = [alert_tag
                             for alert_tag in self.alerts.iterkeys()
                             if alert_tag.startswith(tag)]

            if len(matching_tags) == 1:
                tag = matching_tags[0]
                alert = self.alerts.get(tag)
            elif not matching_tags:
                bot.sendMessage(sender,
                                "No live alerts with tag \"%s\"." % tag)
                return
            else:
                bot.sendMessage(sender,
                                "Ambiguous tag. Prefix matches: " +
                                ", ".join('"%s"' % s for s in matching_tags) +
                                ". Please be more specific.")
                return

        if not alert.muted:
            self.broadcast_from(sender, "acknowledged %s" % tag)
            self._register_mute(tag, sender)
        else:
            bot.sendMessage(sender, "\"%s\" is already acknowledged."
                            % tag)

    def status(self, bot, sender):
        "Show status of all live alerts."

        if not self.alerts:
            bot.sendMessage(sender, "No live alerts. :)")
            return

        now = datetime.datetime.now()
        with bot.message(sender) as m:
            print >>m, "Live alerts:"
            for tag, alert in self.alerts.iteritems():
                print >>m, "<%s>%s seen %dx. started %s ago. last seen %s ago." % (
                    tag,
                    " ack'd by %s." % alert.muted if alert.muted else "",
                    alert.count,
                    pretty_time_span(now - alert.first_seen),
                    pretty_time_span(now - alert.last_seen),
                )


def make_plugin(config, http, jabber, smtp):
    alerts_config = AlertsConfig(config)
    alerter = Alerter(alerts_config, jabber.bot, smtp)

    # create the http resource
    http.root.putChild("alert", BroadcastAlertListener(http, alerter))

    # add commands
    jabber.register_command(alerter.wall)
    jabber.register_command(alerter.ack)
    jabber.register_command(alerter.status)

    # create the watchdog
    watchdog.initialize(http, jabber, alerter)
