import datetime


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
    seconds = int(round(delta.total_seconds(), 0))

    if seconds == 0:
        return "no time"

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


def dehilight(name):
    if name.startswith("@"):
        name = name[1:]
    return u"{}\u200B{}".format(name[0], name[1:])


def constant_time_compare(actual, expected):
    """
    Returns True if the two strings are equal, False otherwise

    The time taken is dependent on the number of characters provided
    instead of the number of characters that match.
    """
    actual_len = len(actual)
    expected_len = len(expected)
    result = actual_len ^ expected_len
    if expected_len > 0:
        for i in xrange(actual_len):
            result |= ord(actual[i]) ^ ord(expected[i % expected_len])
    return result == 0


def fmt_time(time):
    return time.strftime("%H%M")


def parse_time(time_str):
    return datetime.datetime.strptime(time_str, "%H%M").time()


def utc_offset(tz):
    """
    Takes a timezone and returns UTC offset (e.g. -0700) of that timezone,
    for the current time.
    """
    return datetime.datetime.now(tz=tz).strftime("%z")

# Takes in two tuples of (datetime.time, datetime.time) representing a time
# range, and returns true if those ranges overlap.
def timerange_overlap(rangeA, rangeB):
    max_start = max(rangeA[0], rangeB[0])
    min_end = min(rangeA[1], rangeB[1])

    print max_start, min_end
    return max_start < min_end
