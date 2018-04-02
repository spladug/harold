import difflib


class NoHandlerError(Exception):
    def __init__(self, close_matches):
        self.close_matches = close_matches


class Handlers(object):
    def __init__(self):
        self._handlers = {}

    def register(self, key, handler):
        self._handlers[key] = handler

    def process(self, item_key, *args, **kwargs):
        for handler_key, handler in self._handlers.items():
            if handler_key == item_key:
                handler(*args, **kwargs)
                return
        else:
            potential_matches = difflib.get_close_matches(
                item_key, self._handlers, n=1, cutoff=0.6)
            raise NoHandlerError(potential_matches)
