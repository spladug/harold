from collections import deque

from shorturl import make_short_url

class CommitQueue(object):
    def __init__(self):
        self.queue = deque()
        self.consumer = None

    def registerConsumer(self, consumer):
        assert self.consumer is None
        self.consumer = consumer
        while self.queue:
            repository, commit = self.queue.popleft()
            self.consumer.onNewCommit(repository, commit)

    def deregisterConsumer(self, consumer):
        assert self.consumer is not None
        self.consumer = None

    def _pushCommit(self, repository, commit):
        if self.consumer:
            self.consumer.onNewCommit(repository, commit)
        else:
            self.queue.append((repository, commit))

    def addCommit(self, repository, commit):
        d = make_short_url(commit['url'])
        def onUrlShortened(short_url):
            commit['short_url'] = short_url
            self._pushCommit(repository, commit)
        d.addBoth(onUrlShortened)
