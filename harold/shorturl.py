import urllib
from collections import deque

from twisted.internet import reactor
from twisted.internet.defer import Deferred, succeed
from twisted.web.client import Agent


class StringProducer(object):
    def __init__(self, body):
        self.body = body
        self.length = len(body)

    def startProducing(self, consumer):
        consumer.write(self.body)
        return succeed(None)

    def pauseProducing(self):
        pass

    def stopProducing(self):
        pass


class UrlShortener(object):
    def __init__(self):
        self.request_in_flight = False
        self.pending_requests = deque()

    def _onRequestComplete(self):
        self.request_in_flight = False

        if self.pending_requests:
            d = self.pending_requests.popleft()
            d.callback(None)

    def _make_short_url(self, long_url):
        self.request_in_flight = True

        api_uri = "https://git.io/"
        encoded = urllib.urlencode({"url": long_url})
        body_producer = StringProducer(encoded)

        agent = Agent(reactor)
        d = agent.request('POST', api_uri, bodyProducer=body_producer)

        def onRequestComplete(data):
            self._onRequestComplete()
            return data

        def onResponse(response):
            if response.code != 201:
                onRequestComplete(None)
                return long_url

            self._onRequestComplete()
            return response.headers.getRawHeaders("Location")[-1]
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
