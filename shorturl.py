import urllib
from collections import deque

from twisted.internet import reactor
from twisted.internet.protocol import Protocol
from twisted.internet.defer import Deferred
from twisted.web.client import Agent, ResponseDone

class _ResponseCollector(Protocol):
    def __init__(self, finished):
        self.finished = finished
        self.data = []

    def dataReceived(self, bytes):
        self.data.append(bytes)

    def connectionLost(self, reason):
        if reason.check(ResponseDone):
            self.finished.callback("".join(self.data))
        else:
            self.finished.errback(None)

class UrlShortener(object):
    def __init__(self):
        self.request_in_flight = False
        self.pending_requests = deque()

    def _onRequestComplete(self):
        self.request_in_flight = False

        if self.pending_requests:
            d= self.pending_requests.popleft()
            d.callback(None)

    def _make_short_url(self, long_url):
        self.request_in_flight = True

        encoded = urllib.quote_plus(long_url)
        api_uri = "http://is.gd/create.php?format=simple&url=%s" % encoded

        agent = Agent(reactor)
        d = agent.request('GET', api_uri)

        def onRequestComplete(data):
            self._onRequestComplete()
            return data

        def onResponse(response):
            if response.code != 200:
                onRequestComplete(None)
                return long_url

            bodyReceived = Deferred()
            response.deliverBody(_ResponseCollector(bodyReceived))
            bodyReceived.addBoth(onRequestComplete)
            return bodyReceived
        d.addCallback(onResponse)

        def onError(failure):
            return long_url
        d.addErrback(onError)
        d.addErrback(onRequestComplete)

        return d

    def _start_another_request(self, ignored, long_url):
        return self._make_short_url(long_url)

    def make_short_url(self, long_url):
        if not self.request_in_flight:
            return self._make_short_url(long_url)

        d = Deferred()
        d.addCallback(self._start_another_request, long_url)
        self.pending_requests.append(d)
        return d
