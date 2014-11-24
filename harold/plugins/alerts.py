import datetime
import functools
from email.mime.text import MIMEText

from twisted.internet import reactor

from harold.plugins.http import ProtectedResource
from harold.conf import PluginConfig, Option, tup
from harold.utils import pretty_time_span
from harold.plugins import watchdog


def make_short_name(jid):
    short_name = jid.split('@')[0]
    return short_name


def strip_resource_id(jid):
    return jid.partition("/")[0]


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


class Quiet(object):
    pass


class Alerter(object):
    def __init__(self, config, jabber, smtp):
        self.config = config
        self.alerts = {}
        self.quiets = {}
        self.maintenance = None

        senders = {}
        if jabber:
            self.jabber_bot = jabber.bot
            senders["jabber"] = self._send_jabber

        if smtp:
            self.smtp = smtp
            senders["smtp"] = self._send_smtp

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
        if recipient not in self.quiets:
            self.jabber_bot.sendMessage(recipient, message)

    def broadcast(self, message):
        for recipient in self.recipients:
            recipient(message)

    def alert(self, tag, message):
        alert = self._register_alert(tag)
        if not self.maintenance and not alert.muted:
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

        if tag == '-a':
            self.broadcast_from(sender, "acknowledged all")
            for alert_tag in self.alerts.iterkeys():
                self._register_mute(alert_tag, sender)
            return

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
            with bot.message(sender) as m:
                if self.maintenance:
                    print >> m, "IN MAINTENANCE"
                print >> m, "No live alerts. :)"
            return

        now = datetime.datetime.now()
        with bot.message(sender) as m:
            if self.maintenance:
                print >>m, "IN MAINTENANCE"

            print >>m, "Live alerts:"
            for tag, alert in self.alerts.iteritems():
                print >>m, ("<%s>%s seen %dx. started %s ago. "
                            "last seen %s ago.") % (
                    tag,
                    " ack'd by %s." % alert.muted if alert.muted else "",
                    alert.count,
                    pretty_time_span(now - alert.first_seen),
                    pretty_time_span(now - alert.last_seen),
                )

    def _register_quiet(self, sender, duration):
        quiet = Quiet()
        quiet.user = make_short_name(sender)
        quiet.expirator = reactor.callLater(
            duration,
            self._deregister_quiet,
            sender
        )
        quiet.expiration = (datetime.datetime.now() +
                            datetime.timedelta(seconds=duration))
        self.quiets[sender] = quiet

    def _deregister_quiet(self, sender):
        if sender in self.quiets:
            del self.quiets[sender]

    def stfu(self, bot, sender, hours):
        "Mute all alerts for a specified period of time."

        hours = int(hours)
        self._register_quiet(strip_resource_id(sender), hours * 3600)
        bot.sendMessage(sender,
                        "You will not receive any broadcasts for %d hours. "
                        'Say "back" to cancel and start receiving messages'
                        "again." % hours)

    def back(self, bot, sender):
        "Unmute alerts."

        sender = strip_resource_id(sender)
        if sender in self.quiets:
            self._deregister_quiet(sender)
            bot.sendMessage(sender, "Welcome back.")
        else:
            bot.sendMessage(sender, "You were here all along.")

    def who(self, bot, sender):
        "Get a list of people marked unavailable"

        if not self.quiets:
            bot.sendMessage(sender, "Everyone's listening!")
        else:
            with bot.message(sender) as m:
                print >> m, "The following users are unavailable:"
                for quiet in self.quiets.itervalues():
                    print >> m, "<%s> until %s" % (quiet.user,
                                           quiet.expiration.strftime("%H:%M"))

    def maint(self, bot, sender, minutes):
        "Silence alerts globally for a specified number of minutes."

        if not self.maintenance:
            minutes = int(minutes)
            self.maintenance = reactor.callLater(
                minutes * 60,
                self._end_maintenance,
            )
            bot.sendMessage(
                sender,
                "Maintenance window lasting %d minutes started. Say "
                '"endmaint" to end it early.' % minutes,
            )
        else:
            bot.sendMessage(sender, "Maintenance already in progress.")

    def _end_maintenance(self):
        if self.maintenance and self.maintenance.active():
            self.maintenance.cancel()
        self.maintenance = None

    def endmaint(self, bot, sender):
        "End a maintenance window, re-enabling alerts."

        if self.maintenance:
            self._end_maintenance()
            bot.sendMessage(sender, "Maintenance ended. How'd it go?")
        else:
            bot.sendMessage(sender, "There is no maintenance window active.")


def make_plugin(config, http, jabber=None, smtp=None):
    alerts_config = AlertsConfig(config)
    alerter = Alerter(alerts_config, jabber, smtp)

    # create the http resource
    http.root.putChild("alert", BroadcastAlertListener(http, alerter))

    # add commands
    if jabber:
        jabber.register_command(alerter.wall)
        jabber.register_command(alerter.ack)
        jabber.register_command(alerter.status)
        jabber.register_command(alerter.stfu)
        jabber.register_command(alerter.back)
        jabber.register_command(alerter.who)
        jabber.register_command(alerter.maint)
        jabber.register_command(alerter.endmaint)

    # create the watchdog
    watchdog.initialize(http, jabber, alerter)
