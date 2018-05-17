import collections
import json
import re
import traceback
import urllib

from autobahn.twisted.websocket import (
    WebSocketClientFactory,
    WebSocketClientProtocol,
)
from twisted.application.internet import ClientService
from twisted.internet import reactor
from twisted.internet.defer import succeed, inlineCallbacks, returnValue, Deferred
from twisted.internet.endpoints import clientFromString
from twisted.internet.interfaces import IStreamClientEndpoint
from twisted.web.client import Agent, HTTPConnectionPool, readBody
from twisted.web.http_headers import Headers
from zope.interface import implementer

from harold.conf import PluginConfig, Option
from harold.handlers import Handlers, NoHandlerError
from harold.plugin import Plugin


PROVIDES_HAROLD_PLUGINS = ["irc"]


class SlackConfig(PluginConfig):
    token = Option(str)


class FormEncodedBodyProducer(object):
    def __init__(self, data):
        encoded = urllib.urlencode(
            {k: unicode(v).encode('utf-8') for k, v in data.iteritems()})
        self.length = len(encoded)
        self.body = encoded

    def startProducing(self, consumer):
        consumer.write(self.body)
        return succeed(None)

    def pauseProducing(self):
        pass

    def stopProducing(self):
        pass


class SlackWebClientError(Exception):
    pass


class SlackWebClientResponseError(SlackWebClientError):
    def __init__(self, code, payload):
        self.code = code

        del payload["ok"]
        del payload["error"]
        self.args = payload

        super(SlackWebClientResponseError, self).__init__(
            "%r: %r" % (self.code, self.args))


class SlackWebClientRatelimitedError(SlackWebClientError):
    def __init__(self, retry_after):
        self.retry_after = retry_after
        super(SlackWebClientRatelimitedError, self).__init__(
            "ratelimited: retry_after=%d" % self.retry_after)


QueuedRequest = collections.namedtuple("QueuedRequest", "deferred params")


class SlackWebClient(object):
    def __init__(self, token):
        self._pool = HTTPConnectionPool(reactor)
        self._token = token
        self._queues = collections.defaultdict(list)
        self._retry_timers = {}

        self._pool._factory.noisy = False

    @inlineCallbacks
    def make_request(self, method, **params):
        if not self._retry_timers.get(method):
            try:
                response = yield self._make_request(method, **params)
                returnValue(response)
            except SlackWebClientRatelimitedError as exc:
                print("Slack ratelimit hit for %r, retrying in %d seconds." %
                      (method, exc.retry_after))
                self._schedule_retry_timer(method, exc.retry_after)

        # either we were already blocked on ratelimit or we just got a
        # ratelimit response, so we'll queue up this request to be tried when
        # it's OK to do so.
        d = Deferred()
        request = QueuedRequest(d, params)
        self._queues[method].append(request)
        response = yield d
        returnValue(response)

    @inlineCallbacks
    def make_paginated_request(self, method, paginated_field, **params):
        paginated_params = {}
        paginated_params.update(params)
        paginated_params["limit"] = 200

        results = []

        while True:
            response = yield self.make_request(method, **paginated_params)

            results.extend(response[paginated_field])

            next_cursor = response.get("response_metadata", {}).get("next_cursor")
            if not next_cursor:
                break
            paginated_params["cursor"] = next_cursor

        returnValue(results)

    def _schedule_retry_timer(self, method, retry_after):
        current_timer = self._retry_timers.get(method)
        if current_timer and current_timer.active():
            current_timer.cancel()

        timer = reactor.callLater(retry_after, self._drain_queue, method)
        self._retry_timers[method] = timer

    @inlineCallbacks
    def _drain_queue(self, method):
        self._retry_timers[method] = None

        queue = self._queues[method]
        while queue:
            request = queue[0]

            try:
                response = yield self._make_request(method, **request.params)
                request.deferred.callback(response)
            except SlackWebClientRatelimitedError as exc:
                print("Slack ratelimit hit for %r while flushing backlog, %d left in queue." %
                      (method, len(queue)))
                self._schedule_retry_timer(method, exc.retry_after)
                break
            except SlackWebClientError as exc:
                request.deferred.errback(exc)

            queue.pop(0)

    @inlineCallbacks
    def _make_request(self, method, **params):
        headers = Headers({
            "User-Agent": ["Harold (neil@reddit.com)"],
            "Content-Type": ["application/x-www-form-urlencoded"],
        })

        body_data = {"token": self._token}
        body_data.update(params)
        body_producer = FormEncodedBodyProducer(body_data)

        agent = Agent(reactor, pool=self._pool)
        response = yield agent.request(
            "POST",
            "https://slack.com/api/" + method,
            headers,
            body_producer,
        )
        body = yield readBody(response)
        data = json.loads(body)

        if response.code == 429:
            retry_after = int(response.headers.getRawHeaders("Retry-After")[0])
            raise SlackWebClientRatelimitedError(retry_after)

        if not data["ok"]:
            raise SlackWebClientResponseError(data["error"], data)

        warnings = data.get("warnings")
        if warnings:
            # TODO: use real logger
            print("WARNING FROM SLACK: %s" % warnings)

        returnValue(data)


@implementer(IStreamClientEndpoint)
class SlackEndpoint(object):
    def __init__(self, api_client):
        self._api_client = api_client

    @inlineCallbacks
    def connect(self, factory):
        print("Connecting to Slack RTM...")
        data = yield self._api_client.make_request("rtm.connect")
        url = data["url"]

        factory.setSessionParameters(url)
        endpoint = clientFromString(
            reactor,
            "{protocol}:host={host}:port={port}:timeout=10".format(
                protocol="tls" if factory.isSecure else "tcp",
                host=factory.host,
                port=factory.port,
            )
        )
        ws = yield endpoint.connect(factory)
        returnValue(ws)


class SlackClientProtocol(WebSocketClientProtocol):
    def onMessage(self, raw_payload, is_binary):
        if is_binary:
            return

        payload = json.loads(raw_payload)
        self.factory.onMessage(payload)


class SlackClientFactory(WebSocketClientFactory):
    protocol = SlackClientProtocol
    noisy = False

    def __init__(self, plugin, **kwargs):
        self._plugin = plugin
        super(SlackClientFactory, self).__init__(**kwargs)

    def onMessage(self, payload):
        self._plugin._onMessage(payload)


class SlackBot(object):
    USER_RE = re.compile("@([A-Za-z0-9._-]+)")
    CHANNEL_RE = re.compile("(#[A-Za-z0-9_-]+)")

    def __init__(self, api_client, data_cache):
        self._api_client = api_client
        self._data_cache = data_cache

    @inlineCallbacks
    def set_topic(self, channel_name, topic):
        channel = yield self._data_cache.get_channel_by_name(channel_name)

        try:
            yield self._api_client.make_request(
                "channels.setTopic",
                channel=channel["id"],
                topic=topic,
            )
        except SlackWebClientError as exc:
            print("Failed while setting topic in %s: %s" % (channel_name, exc))

    @inlineCallbacks
    def send_message(self, channel_name, message):
        users = yield self._data_cache.get_users()
        users_by_name = {u["name"]: u for u in users.itervalues()}
        def replace_user_mention(m):
            mentioned_name = m.group(1)
            try:
                user = users_by_name[mentioned_name]
            except KeyError:
                return mentioned_name

            return "<@" + user["id"] + ">"
        message = self.USER_RE.sub(replace_user_mention, message)

        channels = yield self._data_cache.get_channels()
        channels_by_name = {"#" + c["name"]: c for c in channels.itervalues()}
        def replace_channel_mention(m):
            mentioned_channel = m.group(1)
            try:
                channel = channels_by_name[mentioned_channel]
            except KeyError:
                return mentioned_channel

            return "<#" + channel["id"] + ">"
        message = self.CHANNEL_RE.sub(replace_channel_mention, message)

        try:
            channel = channels_by_name[channel_name]
        except KeyError:
            print("Attempted to send message to unknown channel: %s" % channel_name)

        try:
            yield self._api_client.make_request(
                "chat.postMessage",
                channel=channel["id"],
                text=message,
                as_user=True,
            )
        except SlackWebClientError as exc:
            print("Failed while sending message to %s: %s" % (channel_name, exc))


class SlackDataCache(object):
    def __init__(self, api_client):
        self._api_client = api_client
        self._wait_for_init = Deferred()
        self._self = {}
        self._users = {}
        self._channels = {}

    @inlineCallbacks
    def initialize(self):
        if not self._wait_for_init:
            self._wait_for_init = Deferred()

        self._self = yield self._api_client.make_request("auth.test")

        users = yield self._api_client.make_paginated_request(
            "users.list", "members")
        for user in users:
            self._users[user["id"]] = user

        channels = yield self._api_client.make_paginated_request(
            "channels.list", "channels", exclude_members=True)
        for channel in channels:
            self._channels[channel["id"]] = channel

        print("Slack data cache initialized.")
        self._wait_for_init.callback(None)
        self._wait_for_init = None

    @inlineCallbacks
    def get_self(self):
        if self._wait_for_init:
            yield self._wait_for_init
        returnValue(self._self)

    @inlineCallbacks
    def get_users(self):
        if self._wait_for_init:
            yield self._wait_for_init
        returnValue(self._users)

    @inlineCallbacks
    def get_user_by_id(self, id):
        users = yield self.get_users()
        returnValue(users[id])

    @inlineCallbacks
    def get_channels(self):
        if self._wait_for_init:
            yield self._wait_for_init
        returnValue(self._channels)

    @inlineCallbacks
    def get_channel_by_id(self, id):
        channels = yield self.get_channels()
        returnValue(channels[id])

    @inlineCallbacks
    def get_channel_by_name(self, name):
        if name.startswith("#"):
            name = name[1:]

        channels = yield self.get_channels()
        for channel in channels.itervalues():
            if name == channel["name"]:
                returnValue(channel)
        returnValue(None)

    def onUserChange(self, payload):
        user = payload["user"]
        self._users[user["id"]] = user

    def onChannelChange(self, payload):
        event_type = payload["type"]
        channel = payload["channel"]

        if event_type == "channel_deleted":
            del self._channels[channel]
        elif event_type == "channel_created":
            self._channels[channel["id"]] = channel
        elif event_type == "channel_rename":
            self._channels[channel["id"]]["name"] = channel["name"]


class SlackPlugin(Plugin):
    def __init__(self, api_client):
        super(SlackPlugin, self).__init__()

        self._handlers = Handlers()
        self._data_cache = SlackDataCache(api_client)
        self._bot = SlackBot(api_client, self._data_cache)

    @property
    def bot(self):
        return self._bot

    def register_command(self, handler):
        self._handlers.register(handler.__name__, handler)

    def _onMessage(self, payload):
        event_type = payload["type"]

        if event_type == "message":
            self._onChat(payload)
        elif event_type == "user_change":
            self._data_cache.onUserChange(payload)
        elif event_type.startswith("channel_"):
            self._data_cache.onChannelChange(payload)
        elif event_type == "hello":
            print("Connected to Slack RTM!")
            self._data_cache.initialize()

    @inlineCallbacks
    def _onChat(self, payload):
        if payload.get("subtype") == "bot_message":
            returnValue(None)

        if payload.get("bot_id") is not None:
            returnValue(None)

        try:
            words = payload["text"].split()
        except KeyError:
            returnValue(None)

        if len(words) < 2:
            returnValue(None)

        self_info = yield self._data_cache.get_self()
        my_id = "<@" + self_info["user_id"] + ">"
        my_name = ("harold", self_info["user"])

        mention, command, args = (words[0], words[1].lower(), words[2:])
        if not (mention.lower().startswith(my_name) or my_id in mention):
            returnValue(None)

        channel_id = payload["channel"]
        channel_info = yield self._data_cache.get_channel_by_id(channel_id)
        channel = '#' + channel_info["name"]

        user = yield self._data_cache.get_user_by_id(payload["user"])
        sender_nick = user["name"]

        try:
            self._handlers.process(command, self.bot, sender_nick, channel, *args)
        except NoHandlerError as exc:
            if exc.close_matches:
                self.bot.send_message(channel, "@%s: did you mean `%s`?" % (sender_nick, exc.close_matches[0]))
        except:
            print("Exception while handling command %r" % words)
            traceback.print_exc()


def make_plugin(config, http=None):
    slack_config = SlackConfig(config)

    api_client = SlackWebClient(slack_config.token)
    endpoint = SlackEndpoint(api_client)
    plugin = SlackPlugin(api_client)
    factory = SlackClientFactory(
        plugin=plugin,
        useragent="Harold (neil@reddit.com)",
    )
    factory.setProtocolOptions(
        autoPingInterval=5,
        autoPingTimeout=10,
    )
    service = ClientService(endpoint, factory)
    plugin.add_service(service)
    return plugin
