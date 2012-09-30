class Dispatcher(object):
    def __init__(self):
        self.consumer = None
        self.queue = []

    def registerConsumer(self, consumer):
        assert self.consumer is None
        self.consumer = consumer

        # throw all the queued events at the consumer
        for fn_name, args, kwargs in self.queue:
            self._apply(fn_name, args, kwargs)
        self.queues = []

    def deregisterConsumer(self, consumer):
        assert self.consumer is not None
        self.consumer = None

    def _apply(self, fn_name, args, kwargs):
        fn = getattr(self.consumer, fn_name)
        fn(*args, **kwargs)

    def _apply_or_enqueue(self, fn_name, args, kwargs):
        if self.consumer:
            self._apply(fn_name, args, kwargs)
        else:
            self.queue.append((fn_name, args, kwargs))

    def __getattr__(self, name):
        def wrapper(*args, **kwargs):
            self._apply_or_enqueue(name, args, kwargs)
        return wrapper
