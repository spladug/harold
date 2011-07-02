import urllib

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

def make_short_url(long_url):
    encoded = urllib.quote_plus(long_url)
    api_uri = "http://is.gd/create.php?format=simple&url=%s" % encoded

    agent = Agent(reactor)
    d = agent.request('GET', api_uri)

    def onResponse(response):
        if response.code != 200:
            return long_url

        bodyReceived = Deferred()
        response.deliverBody(_ResponseCollector(bodyReceived))
        return bodyReceived
    d.addCallback(onResponse)

    def onError(failure):
        return long_url
    d.addErrback(onError)

    return d
