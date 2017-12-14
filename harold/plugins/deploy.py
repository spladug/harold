import datetime
import functools
import hashlib
import hmac
import json
import time

from twisted.web import resource
from twisted.internet import reactor, task

from harold.plugins.http import ProtectedResource
from harold.conf import PluginConfig, Option
from harold.utils import (
    constant_time_compare,
    dehilight,
    pretty_and_accurate_time_span,
)


# how old/new a deploy status request's timestamp can be to be allowed
MAX_SKEW_SECONDS = 60


class DeployConfig(PluginConfig):
    channel = Option(str)
    deploy_ttl = Option(int)
    conch_emoji = Option(str, default=":shell:")


class DeployListener(ProtectedResource):
    def __init__(self, http, monitor):
        ProtectedResource.__init__(self, http)
        self.monitor = monitor


class DeployStatusListener(resource.Resource):
    isLeaf = True

    def __init__(self, secret, monitor):
        self.secret = secret
        self.monitor = monitor
        resource.Resource.__init__(self)

    def render_GET(self, request):
        header_name = "X-Signature"

        if not request.requestHeaders.hasHeader(header_name):
            request.setResponseCode(401)
            return ""

        try:
            header_value = request.requestHeaders.getRawHeaders(header_name)[0]
            timestamp, sep, signature = header_value.partition(":")

            if sep != ":":
                raise Exception("unparseable")

            expected = hmac.new(self.secret, timestamp, hashlib.sha256).hexdigest()
            if not constant_time_compare(signature, expected):
                raise Exception("invalid signature")

            if abs(time.time() - int(timestamp)) > MAX_SKEW_SECONDS:
                raise Exception("too much skew")
        except:
            request.setResponseCode(403)
            return ""

        request.setHeader("Content-Type", "application/json")
        return json.dumps({
            "time_status": self.monitor.current_time_status(),
            "busy": bool(self.monitor.deploys),
            "hold": self.monitor.current_hold,
        })


class DeployBeganListener(DeployListener):
    isLeaf = True

    def _handle_request(self, request):
        id = unicode(request.args['id'][0], 'utf-8')
        who = request.args['who'][0]
        args = request.args['args'][0]
        log_path = unicode(request.args['log_path'][0], 'utf-8')
        count = int(request.args['count'][0])
        self.monitor.onPushBegan(id, who, args, log_path, count)


class DeployEndedListener(DeployListener):
    isLeaf = True

    def _handle_request(self, request):
        id = unicode(request.args['id'][0], 'utf-8')

        try:
            failed_hosts_arg = request.args["failed_hosts"][0]
        except KeyError:
            failed_hosts = []
        else:
            failed_hosts = filter(None, failed_hosts_arg.decode("utf-8").split(","))

        self.monitor.onPushEnded(id, failed_hosts)


class DeployErrorListener(DeployListener):
    isLeaf = True

    def _handle_request(self, request):
        id = unicode(request.args['id'][0], 'utf-8')
        error = request.args['error'][0]
        self.monitor.onPushError(id, error)


class DeployAbortedListener(DeployListener):
    isLeaf = True

    def _handle_request(self, request):
        id = unicode(request.args['id'][0], 'utf-8')
        reason = request.args['reason'][0]
        self.monitor.onPushAborted(id, reason)


class DeployProgressListener(DeployListener):
    isLeaf = True

    def _handle_request(self, request):
        id = unicode(request.args['id'][0], 'utf-8')
        host = request.args['host'][0]
        index = float(request.args['index'][0])
        self.monitor.onPushProgress(id, host, index)


class OngoingDeploy(object):
    pass


class DeployMonitor(object):
    def __init__(self, config, irc):
        self.config = config
        self.irc = irc
        self.deploys = {}
        self.current_hold = None
        self.current_conch = ""
        self.conch_expirator = None
        self.queue = []
        self.current_topic = self._make_topic()

        looper = task.LoopingCall(self._update_topic)
        looper.start(10)

    def help(self, irc, sender, channel, *args):
        if channel != self.config.channel:
            return

        irc.send_message(channel, "see: https://github.com/spladug/harold/wiki")

    def status(self, irc, sender, channel):
        "Get the status of currently running deploys."
        if channel != self.config.channel:
            return

        reply = functools.partial(self.irc.bot.send_message, channel)

        if not self.deploys:
            reply("@%s: there are currently no active deploys." % sender)

        deploys = sorted(self.deploys.values(), key=lambda d: d.when)
        for d in deploys:
            status = ""
            if d.where:
                percent = (float(d.completion) / d.host_count) * 100.0
                status = " (which is on %s -- %d%% done)" % (d.where, percent)

            reply('@%s: %s started deploy "%s"%s at %s with args "%s". log: %s' %
                  (sender, d.who, d.id, status, d.when.strftime("%H:%M"),
                   d.args, d.log_path))

    def _hold(self, reason):
        if not reason:
            reason_text = "no reason given"
        else:
            reason_text = " ".join(reason)
        self.current_hold = reason_text
        self._update_topic()

    def hold(self, irc, sender, channel, *reason):
        if channel != self.config.channel:
            return
        self._hold(reason)

    def hold_all(self, irc, sender, channel, *reason):
        self._hold(reason)

    def _unhold(self):
        self.current_hold = None
        self._update_topic()

    def unhold(self, irc, sender, channel, *ignored):
        if channel != self.config.channel:
            return
        self._unhold()

    def unhold_all(self, irc, sender, channel, *ignored):
        self._unhold()

    def acquire(self, irc, sender, channel, *ignored):
        if channel != self.config.channel:
            return

        if sender in self.queue:
            self.irc.bot.send_message(
                channel, "@%s: you are already in the queue" % sender)
            return
        elif self.queue:
            if len(self.queue) > 1:
                self.irc.bot.send_message(
                    channel, "@%s: ok -- you're in the queue" % sender)
            else:
                self.irc.bot.send_message(
                    channel, "@%s: ok -- you're in the queue and you're next so please be ready!" % sender)

        self.queue.append(sender)
        self._update_topic()
        self._update_conch()

    def aquire(self, irc, sender, channel, *ignored):
        if channel != self.config.channel:
            return

        self.irc.bot.send_message(channel, "what's a quire?")
        self.acquire(irc, sender, channel)

    def _update_conch(self):
        if self.queue:
            new_conch = self.queue[0]
            if new_conch != self.current_conch:
                self._start_conch_expiration()

                self.irc.bot.send_message(self.config.channel,
                    "@%s: you have the %s" % (new_conch, self.config.conch_emoji))
                if len(self.queue) > 1:
                    self.irc.bot.send_message(
                        self.config.channel,
                        "@%s: you're up next. please get ready!" % self.queue[1])
        else:
            self._cancel_conch_expiration()
            new_conch = None
        self.current_conch = new_conch

    def _start_conch_expiration(self):
        self._cancel_conch_expiration()
        self.conch_expirator = reactor.callLater(60 * 5, self._warn_conch_expiration)

    def _cancel_conch_expiration(self):
        if self.conch_expirator and self.conch_expirator.active():
            self.conch_expirator.cancel()
        self.conch_expirator = None

    def _warn_conch_expiration(self):
        self.irc.bot.send_message(
            self.config.channel,
            '@%s: :eyes: are you still using the %s? please reply with "yes" if '
            "so or else I'll have to kick you!" % (self.queue[0], self.config.conch_emoji)
        )
        self.conch_expirator = reactor.callLater(60 * 2, self._expire_conch)

    def _expire_conch(self):
        self.conch_expirator = None
        self.irc.bot.send_message(
            self.config.channel,
            "@%s: this is where I would have kicked you when this feature is out of testing" % self.queue[0],
        )
        #self.queue.pop(0)
        #self._update_conch()
        #self._update_topic()

    def yes(self, irc, sender, channel, *ignored):
        if channel != self.config.channel:
            return

        if sender != self.queue[0]:
            self.irc.bot.send_message(self.config.channel, "sorry, but @%s has to say it!" % self.queue[0])
            return

        self._cancel_conch_expiration()
        self.irc.bot.send_message(self.config.channel, "OK, understood. :disappear:")

    def release(self, irc, sender, channel, *ignored):
        if channel != self.config.channel:
            return

        if sender not in self.queue:
            self.irc.bot.send_message(
                channel, "@%s: you are not in the queue" % sender)
            return

        self.queue.remove(sender)
        self._update_conch()
        self._update_topic()

    def jump(self, irc, sender, channel):
        if channel != self.config.channel:
            return

        if self.queue and self.queue[0] == sender:
            self.irc.bot.send_message(
                channel, "@%s: you already have the %s" % (sender, self.config.conch_emoji))
            return

        if sender in self.queue:
            self.queue.remove(sender)
        self.queue.insert(0, sender)
        self._update_conch()
        self._update_topic()

    def enqueue(self, irc, sender, channel, *users):
        if channel != self.config.channel:
            return

        for user in users:
            if user not in self.queue:
                self.queue.append(user)

        self._update_topic()
        self._update_conch()

    def kick(self, irc, sender, channel, user):
        if channel != self.config.channel:
            return

        if user not in self.queue:
            self.irc.bot.send_message(
                channel, "@%s: %s is not in the queue" % (sender, dehilight(user)))
            return

        self.queue.remove(user)
        self._update_conch()
        self._update_topic()

        if user == sender:
            self.irc.bot.send_message(
                channel, ":nelson: stop kicking yourself! stop kicking yourself!")

    def refresh(self, irc, sender, channel):
        if channel != self.config.channel:
            return
        self._update_topic(force=True)

    def current_time_status(self):
        date = datetime.date.today()
        time = datetime.datetime.now().time()

        # always after 9am
        if time < datetime.time(9, 0):
            return "after_hours"

        if date.weekday() in (0, 1, 2, 3):
            # monday through thursday, before 4pm
            if time < datetime.time(16, 0):
                return "work_time"
            elif time < datetime.time(17, 0):
                return "cleanup_time"
            else:
                return "after_hours"
        else:
            # no work on the weekend
            return "after_hours"

    def _make_topic(self):
        deploy_count = len(self.deploys)

        if deploy_count == 0:
            if self.current_hold is not None:
                status = ":no_entry_sign: deploys ON HOLD (%s)" % self.current_hold
            else:
                time_status = self.current_time_status()

                if time_status == "work_time":
                    status = ":office: working hours, normal deploy rules apply"
                elif time_status == "cleanup_time":
                    status = ":hand: it's late, fixup/polish deploys only"
                else:
                    status = ":warning: after hours, emergency deploys only"
        elif deploy_count == 1:
            deploy = self.deploys.values()[0]
            status = ":hourglass: %s is deploying" % deploy.who
        else:  # > 1
            status = ":hourglass: %d deploys in progress" % deploy_count

        return " | ".join((
            status,
            "%s has the %s" % ("@" + self.queue[0] if self.queue else "no one", self.config.conch_emoji),
            "queue: %s" % (", ".join(map(dehilight, self.queue[1:])) or "<empty>"),
        ))

    def _update_topic(self, force=False):
        new_topic = self._make_topic()
        if force or new_topic != self.current_topic:
            self.irc.bot.set_topic(self.config.channel, new_topic)
            self.current_topic = new_topic

    def _remove_deploy(self, id):
        deploy = self.deploys.get(id)
        if not deploy:
            return None, None

        if deploy.expirator.active():
            deploy.expirator.cancel()

        del self.deploys[id]
        return deploy.who, datetime.datetime.now() - deploy.when

    def onPushBegan(self, id, who, args, log_path, count):
        self._cancel_conch_expiration()

        deploy = OngoingDeploy()
        deploy.id = id
        deploy.when = datetime.datetime.now()
        deploy.who = who
        deploy.args = args
        deploy.log_path = log_path
        deploy.quadrant = 1
        deploy.where = None
        deploy.completion = None
        deploy.host_count = count
        deploy.expirator = reactor.callLater(self.config.deploy_ttl,
                                             self._remove_deploy, id)
        self.deploys[id] = deploy

        self._update_topic()
        self.irc.bot.send_message(self.config.channel,
                                  '@%s started deploy "%s" '
                                  "with args %s" % (who, id, args))

    def onPushProgress(self, id, host, index):
        deploy = self.deploys.get(id)
        if not deploy:
            return

        deploy.expirator.delay(self.config.deploy_ttl)
        deploy.completion = index
        deploy.where = host

        # don't get spammy for tiny pushes
        if deploy.host_count < 8:
            return

        # don't care about "100%" since it'll be quickly followed by "complete"
        if deploy.quadrant > 3:
            return

        percent = float(index) / deploy.host_count
        if percent < (deploy.quadrant * .25):
            return

        self.irc.bot.send_message(self.config.channel,
                                  """deploy "%s" by @%s is %d%% complete.""" %
                                  (id, deploy.who, deploy.quadrant * 25))
        deploy.quadrant += 1

    def onPushEnded(self, id, failed_hosts):
        deploy = self.deploys.get(id)
        who, duration = self._remove_deploy(id)

        if not self.deploys:
            self._start_conch_expiration()

        if not who:
            return

        self.irc.bot.send_message(
            self.config.channel,
            """deploy "%s" by @%s is complete. """
            "Took %s." % (id, who, pretty_and_accurate_time_span(duration))
        )
        self._update_topic()

        if failed_hosts:
            self.irc.bot.send_message(
                "#monitoring",
                "Deploy `%s` in %s encountered errors on the "
                    "following hosts: %s. See %s for more information." % (
                        id, self.config.channel, ", ".join(sorted(failed_hosts)),
                        deploy.log_path)
            )

    def onPushError(self, id, error):
        deploy = self.deploys.get(id)
        if not deploy:
            return

        deploy.expirator.delay(self.config.deploy_ttl)
        self.irc.bot.send_message(self.config.channel,
                                  ("""deploy "%s" by @%s encountered """
                                   "an error: %s") %
                                  (id, deploy.who, error))

    def onPushAborted(self, id, reason):
        who, duration = self._remove_deploy(id)

        if not self.deploys:
            self._start_conch_expiration()

        if not who:
            return

        self.irc.bot.send_message(self.config.channel,
                                  """deploy "%s" by @%s aborted (%s)""" %
                                  (id, who, reason))
        self._update_topic()


def make_plugin(config, http, irc):
    deploy_config = DeployConfig(config)
    monitor = DeployMonitor(deploy_config, irc)

    # yay channels
    irc.channels.add(deploy_config.channel)

    # set up http api
    deploy_root = resource.Resource()
    http.root.putChild('deploy', deploy_root)
    deploy_root.putChild('status', DeployStatusListener(http.hmac_secret, monitor))
    deploy_root.putChild('begin', DeployBeganListener(http, monitor))
    deploy_root.putChild('end', DeployEndedListener(http, monitor))
    deploy_root.putChild('abort', DeployAbortedListener(http, monitor))
    deploy_root.putChild('error', DeployErrorListener(http, monitor))
    deploy_root.putChild('progress', DeployProgressListener(http, monitor))

    # register our irc commands
    irc.register_command(monitor.status)
    irc.register_command(monitor.hold)
    irc.register_command(monitor.unhold)
    irc.register_command(monitor.hold_all)
    irc.register_command(monitor.unhold_all)
    irc.register_command(monitor.acquire)
    irc.register_command(monitor.aquire)
    irc.register_command(monitor.release)
    irc.register_command(monitor.jump)
    irc.register_command(monitor.kick)
    irc.register_command(monitor.refresh)
    irc.register_command(monitor.help)
    irc.register_command(monitor.enqueue)
    irc.register_command(monitor.yes)
