import re
import urlparse


class Event(object):
    """An event that can have an arbitrary number of listeners that get called
    when the event fires."""
    def __init__(self):
        self.listeners = set()

    def register_listener(self, callable):
        self.listeners.add(callable)
        return callable

    def fire(self, *args, **kwargs):
        for listener in self.listeners:
            listener(*args, **kwargs)

    __iadd__ = register_listener
    __call__ = fire


def pretty_time_span(delta):
    seconds = int(delta.total_seconds())
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    if hours == 1:
        return "1 hour"
    elif hours > 1:
        return "%d hours" % hours
    elif minutes == 1:
        return "1 minute"
    elif minutes > 1:
        return "%d minutes" % minutes
    elif seconds == 1:
        return "1 second"
    else:
        return "%d seconds" % seconds


def pretty_and_accurate_time_span(delta):
    seconds = int(delta.total_seconds())
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)

    parts = []
    if hours == 1:
        parts.append("1 hour")
    elif hours > 1:
        parts.append("%d hours" % hours)

    if minutes == 1:
        parts.append("1 minute")
    elif minutes > 1:
        parts.append("%d minutes" % minutes)

    if seconds == 1:
        parts.append("1 second")
    elif seconds > 1:
        parts.append("%d seconds" % seconds)
    return ", ".join(parts)
