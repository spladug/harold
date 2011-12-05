from twisted.internet import reactor
from twisted.web import resource

from http import ProtectedResource


HEARTBEAT_GRACE_PERIOD = 5 # seconds


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
        service.clear_expiration()
        self._schedule_expiration(tag)

    def _schedule_expiration(self, tag):
        service = self.services[tag]
        service.expirator = reactor.callLater(
            service.interval + HEARTBEAT_GRACE_PERIOD,
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

    def unregister(self, tag):
        if tag not in self.services:
            return

        self.services[tag].clear_expiration()
        del self.services[tag]


def initialize(http, alerter):
    watchdog = Watchdog(alerter)

    http.root.putChild("heartbeat", HeartbeatListener(http, watchdog))
