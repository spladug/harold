import collections
import datetime
import json

from baseplate.file_watcher import FileWatcher

from salon.app import app
from salon.models import db
from salon.models import Event


METRICS_FILE_PATH = "/var/lib/harold/metrics.json"
METRICS_HORIZON_DAYS = 90
FILEWATCHER = FileWatcher(METRICS_FILE_PATH, json.load)


HOLIDAYS = [
    datetime.date(2019, 1, 1),
    datetime.date(2019, 1, 2),
    datetime.date(2019, 1, 21),
    datetime.date(2019, 2, 18),
    datetime.date(2019, 5, 27),
    datetime.date(2019, 7, 4),
    datetime.date(2019, 9, 2),
    datetime.date(2019, 11, 28),
    datetime.date(2019, 11, 29),
    datetime.date(2019, 12, 24),
    datetime.date(2019, 12, 25),
    datetime.date(2019, 12, 31),

    datetime.date(2020, 1, 1),
    datetime.date(2020, 1, 2),
    datetime.date(2020, 1, 20),
    datetime.date(2020, 2, 17),
    datetime.date(2020, 5, 25),
    datetime.date(2020, 6, 19),
    datetime.date(2020, 7, 2),
    datetime.date(2020, 7, 3),
    datetime.date(2020, 8, 21),
    datetime.date(2020, 9, 4),
    datetime.date(2020, 9, 7),
    datetime.date(2020, 11, 3),
    datetime.date(2020, 11, 26),
    datetime.date(2020, 11, 27),
    datetime.date(2020, 12, 24),
    datetime.date(2020, 12, 25),
    datetime.date(2020, 12, 31),
]


@app.context_processor
def add_metrics_horizon():
    return {"metrics_horizon": METRICS_HORIZON_DAYS}


def load_metrics():
    return FILEWATCHER.get_data()


def calculate_p90(data):
    # cribbed from the py3.8 stdlib's statistics.quantiles function
    data = sorted(data)
    ld = len(data)
    m = ld - 1
    n = 10
    result = []
    for i in range(1, n):
        j = i * m // n
        delta = i*m - j*n
        interpolated = (data[j] * (n - delta) + data[j+1] * delta) / n
        result.append(interpolated)
    return result[8]


def business_time_elapsed(start, end):
    now = start
    business_days = 0
    while (end-now).days > 0:
        now += datetime.timedelta(days=1)
        if now.weekday() not in (5, 6) and now.date() not in HOLIDAYS:
            business_days += 1

    time_elapsed = end - now
    return time_elapsed + datetime.timedelta(days=business_days)


class MetricsAggregator(object):
    def __init__(self, base_tags=None):
        self.base_tags = base_tags or {}
        self.counters = collections.defaultdict(
                lambda: collections.defaultdict(collections.Counter))
        self.timers = collections.defaultdict(
                lambda: collections.defaultdict(lambda: collections.defaultdict(list)))

    def increment_counter(self, name, delta=1, tags=None):
        all_tags = self.base_tags.copy()
        all_tags.update(tags or {})
        for tag_name, tag_value in all_tags.items():
            assert tag_value != "*"
            self.counters[tag_name][tag_value.lower()][name] += delta
            self.counters[tag_name]["*"][name] += delta

    def record_duration(self, name, start, end, tags=None):
        duration = business_time_elapsed(start, end)
        all_tags = self.base_tags.copy()
        all_tags.update(tags or {})
        for tag_name, tag_value in all_tags.items():
            assert tag_value != "*"
            self.timers[tag_name][tag_value.lower()][name].append(duration)
            self.timers[tag_name]["*"][name].append(duration)

    def with_default_tags(self, **tags):
        base_tags = self.base_tags.copy()
        base_tags.update(tags)
        aggregator = MetricsAggregator(base_tags=base_tags)
        aggregator.counters = self.counters
        aggregator.timers = self.timers
        return aggregator

    def aggregate(self):
        result = {}

        for tag_name, tags in self.counters.items():
            result.setdefault(tag_name, {})
            for tag_value, metrics in tags.items():
                result[tag_name].setdefault(tag_value, {})
                result[tag_name][tag_value]["counters"] = {
                    name: value for name, value in metrics.items()}

        for tag_name, tags in self.timers.items():
            result.setdefault(tag_name, {})
            for tag_value, metrics in tags.items():
                result[tag_name].setdefault(tag_value, {})
                result[tag_name][tag_value]["timers"] = {}
                for metric_name, timings in metrics.items():
                    if len(timings) < 10:
                        continue

                    p90 = calculate_p90(timings)
                    result[tag_name][tag_value]["timers"][metric_name] = p90.total_seconds()

        return result


class EventCollector(object):
    def __init__(self, metrics):
        self.metrics = metrics
        self.opened_at = None
        self.requested_at = {}
        self.author = None
        self.closed_at = None

    def observe(self, event):
        if event.event == "opened":
            self.opened_at = event.timestamp
            self.author = event.actor
            self.metrics.increment_counter("opened", tags={"user": event.actor})
        elif event.event == "closed":
            self.closed_at = event.timestamp
        elif event.event == "reopened":
            self.closed_at = None
        elif event.event == "review_requested":
            for target in event.info.get("targets", []):
                self.requested_at.setdefault(target, event.timestamp)
                self.metrics.increment_counter("review_requested", tags={"user": target})
        elif event.event == "review_request_removed":
            for target in event.info.get("targets", []):
                requested_at = self.requested_at.pop(target, None)

                if target == event.actor:
                    self.metrics.increment_counter("review_rejected", tags={"user": target})

                    if requested_at:
                        self.metrics.record_duration("review", requested_at, event.timestamp, tags={"user": target})

                if requested_at:
                    self.metrics.increment_counter("review_requested", delta=-1, tags={"user": target})
        elif event.event == "review":
            requested_at = self.requested_at.pop(event.actor, None)
            if requested_at:
                self.metrics.record_duration("review", requested_at, event.timestamp, tags={"user": event.actor})

            self.metrics.increment_counter("review", tags={"user": event.actor})
            self.metrics.increment_counter("review-" + event.info["state"], tags={"user": event.actor})

    def flush(self):
        if self.opened_at:
            now = datetime.datetime.utcnow()
            self.metrics.record_duration("open", self.opened_at, self.closed_at or now, tags={"user": self.author})

            if not self.closed_at:
                for user, requested_at in self.requested_at.items():
                    self.metrics.record_duration("review", requested_at, now, tags={"user": user})


@app.cli.command()
def calculate_metrics():
    metrics = MetricsAggregator()
    collectors = {}

    print("Scanning events...")
    horizon = datetime.datetime.utcnow() - datetime.timedelta(days=METRICS_HORIZON_DAYS)
    query = (Event.query
        .filter(Event.timestamp >= horizon)
        .order_by(db.asc(Event.timestamp))
    )
    for event in query:
        pr_id = "%s#%d" % (event.repository, event.pull_request_id)
        collector = collectors.get(pr_id)

        if not collector:
            tagged_metrics = metrics.with_default_tags(repository=event.repository)
            collector = EventCollector(tagged_metrics)
            collectors[pr_id] = collector

        collector.observe(event)

    for collector in collectors.itervalues():
        collector.flush()

    print("Writing aggregated metrics...")
    aggregated = metrics.aggregate()
    with open(METRICS_FILE_PATH, "w") as f:
        json.dump(aggregated, f)
