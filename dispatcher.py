def queueable(fn):
    """Decorator that appends action to queue if consumer not available."""
    def _queueable(self, *args):
        if self.consumer:
            fn(self, *args)
        else:
            self.queue.append((fn, args))
    return _queueable

class Dispatcher(object):
    def __init__(self):
        self.consumer = None
        self.queue = []

    def registerConsumer(self, consumer):
        assert self.consumer is None
        self.consumer = consumer

        # throw all the queued events at the consumer
        for fn, args in self.queue:
            fn(self, *args)
        self.queues = []

    def deregisterConsumer(self, consumer):
        assert self.consumer is not None
        self.consumer = None

    @queueable
    def send_message(self, channel, message):
        self.consumer.send_message(channel, message)

    @queueable
    def set_topic(self, channel, message):
        self.consumer.set_topic(channel, message)

    @queueable
    def restore_topic(self, channel):
        self.consumer.restore_topic(channel)

