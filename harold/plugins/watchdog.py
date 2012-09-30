import datetime

from twisted.internet import reactor

from harold.plugins.http import ProtectedResource
from harold.utils import pretty_time_span


class WatchdogResource(ProtectedResource):
    isLeaf = True

    def __init__(self, http, watchdog):
        ProtectedResource.__init__(self, http)
        self.watchdog = watchdog


class HeartbeatListener(WatchdogResource):
    def _handle_request(self, request):
        tag = request.args['tag'][0]
        interval = int(request.args['interval'][0])
        self.watchdog.heartbeat(tag, interval)


class WatchedService(object):
    def __init__(self, interval):
        self.interval = interval
        self.expirator = None
        self.last_seen = None
        self.failure_count = 0

    def clear_expiration(self):
        if self.expirator:
            self.expirator.cancel()
        self.expirator = None


class Watchdog(object):
    def __init__(self, alerter):
        self.services = {}
        self.alerter = alerter

    def heartbeat(self, tag, interval):
        if tag not in self.services:
            self.services[tag] = WatchedService(interval)

        service = self.services[tag]
        service.failure_count = 0
        service.interval = interval
        service.clear_expiration()
        service.last_seen = datetime.datetime.now()
        self._schedule_expiration(tag)

    def _schedule_expiration(self, tag):
        service = self.services[tag]
        service.expirator = reactor.callLater(
            service.interval,
            self._heartbeat_missed,
            tag
        )

    def _heartbeat_missed(self, tag):
        if tag not in self.services:
            return

        service = self.services[tag]
        service.failure_count += 1
        self.alerter.alert(tag, "missed heartbeat %d times" % service.failure_count)
        self._schedule_expiration(tag)

    def watches(self, bot, sender):
        "Check the status of all registered services."

        if not self.services:
            bot.sendMessage(sender, "Not watching any services.")
            return

        now = datetime.datetime.now()
        with bot.message(sender) as m:
            print >>m, "Monitored services:"

            for tag, service in self.services.iteritems():
                print >>m, "<%s> %s. last seen %s ago." % (
                    tag,
                    "MISSING for %d heartbeats" % service.failure_count if service.failure_count else "HEALTHY",
                    pretty_time_span(now - service.last_seen)
                )

    def forget(self, bot, sender, tag):
        "Forget the specified service and stop expecting heartbeats from it."

        if tag not in self.services:
            bot.sendMessage(sender, "I'm not watching %s" % tag)
            return

        self.services[tag].clear_expiration()
        del self.services[tag]

        bot.sendMessage(sender, "Nobody liked %s anyway." % tag)


def initialize(http, jabber, alerter):
    watchdog = Watchdog(alerter)

    http.root.putChild("heartbeat", HeartbeatListener(http, watchdog))

    jabber.register_command(watchdog.forget)
    jabber.register_command(watchdog.watches)
