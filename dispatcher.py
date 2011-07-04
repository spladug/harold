from collections import deque


class Dispatcher(object):
    def __init__(self):
        self.queue = deque()
        self.consumer = None

    def registerConsumer(self, consumer):
        assert self.consumer is None
        self.consumer = consumer
        while self.queue:
            channel, message = self.queue.popleft()
            self.send_message(channel, message)

    def deregisterConsumer(self, consumer):
        assert self.consumer is not None
        self.consumer = None

    def send_message(self, channel, message):
        if self.consumer:
            self.consumer.send_message(channel, message)
        else:
            self.queue.append((channel, message))
