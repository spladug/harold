import datetime
import functools

from twisted.web import resource
from twisted.internet import reactor, task

from harold.plugins.http import ProtectedResource
from harold.conf import PluginConfig, Option
from harold.utils import pretty_and_accurate_time_span


class DeployConfig(PluginConfig):
    channel = Option(str)
    deploy_ttl = Option(int)


class DeployListener(ProtectedResource):
    def __init__(self, http, monitor):
        ProtectedResource.__init__(self, http)
        self.monitor = monitor


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
        self.monitor.onPushEnded(id)


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
        self.current_topic = ""
        self.current_conch = ""
        self.queue = []

        looper = task.LoopingCall(self._update_topic)
        looper.start(10)

    def status(self, irc, sender, channel):
        "Get the status of currently running deploys."
        if channel != self.config.channel:
            return

        reply = functools.partial(self.irc.bot.send_message, channel)

        if not self.deploys:
            reply("%s, there are currently no active deploys." % sender)

        deploys = sorted(self.deploys.values(), key=lambda d: d.when)
        for d in deploys:
            status = ""
            if d.where:
                percent = (float(d.completion) / d.host_count) * 100.0
                status = " (which is on %s -- %d%% done)" % (d.where, percent)

            reply('%s, %s started deploy "%s"%s at %s with args "%s". log: %s' %
                  (sender, d.who, d.id, status, d.when.strftime("%H:%M"),
                   d.args, d.log_path))

    def hold(self, irc, sender, channel):
        if channel != self.config.channel:
            return

        if self.current_hold:
            self.irc.bot.send_message(
                channel, "%s, deploys are already on hold" % sender)
            return

        self.current_hold = sender
        self._update_topic()

    def unhold(self, irc, sender, channel):
        if channel != self.config.channel:
            return

        if not self.current_hold:
            self.irc.bot.send_message(
                channel, "%s, deploys are not on hold" % sender)
            return

        self.current_hold = None
        self._update_topic()

    def acquire(self, irc, sender, channel):
        if channel != self.config.channel:
            return

        if sender in self.queue:
            self.irc.bot.send_message(
                channel, "%s, you are already in the queue" % sender)
            return

        self.queue.append(sender)
        self._update_topic()
        self._update_conch()

    def _update_conch(self):
        if self.queue:
            new_conch = self.queue[0]
            if new_conch != self.current_conch:
                self.irc.bot.send_message(self.config.channel,
                    "%s, you have the :shell:" % new_conch)
        else:
            new_conch = None
        self.current_conch = new_conch

    def release(self, irc, sender, channel):
        if channel != self.config.channel:
            return

        if sender not in self.queue:
            self.irc.bot.send_message(
                channel, "%s, you are not in the queue" % sender)
            return

        self.queue.remove(sender)
        self._update_conch()
        self._update_topic()

    def jump(self, irc, sender, channel):
        if channel != self.config.channel:
            return

        if self.queue and self.queue[0] == sender:
            self.irc.bot.send_message(
                channel, "%s, you already have the :shell:" % sender)
            return

        if sender in self.queue:
            self.queue.remove(sender)
        self.queue.insert(0, sender)
        self._update_conch()
        self._update_topic()

    def kick(self, irc, sender, channel, user):
        if channel != self.config.channel:
            return

        if user not in self.queue:
            self.irc.bot.send_message(
                channel, "%s, %s is not in the queue" % (sender, user))
            return

        self.queue.remove(user)
        self._update_conch()
        self._update_topic()

    def is_working_hours(self):
        date = datetime.date.today()
        time = datetime.datetime.now().time()

        # never before 9am
        if time < datetime.time(9, 0):
            return False

        if date.weekday() in (0, 1, 2, 3):
            # monday through thursday, 9-5
            return time < datetime.time(17, 0)
        elif date.weekday() == 4:
            # friday, 9-12
            return time < datetime.time(12, 0)
        else:
            # no work on the weekend
            return False

    def _update_topic(self):
        deploy_count = len(self.deploys)

        if deploy_count == 0:
            if self.current_hold:
                status = ":no_entry_sign: deploys ON HOLD by request of %s" % self.current_hold
            elif not self.is_working_hours():
                status = ":warning: after hours, emergency deploys only"
            else:
                status = ":thumbsup: OK for deploy"
        elif deploy_count == 1:
            deploy = self.deploys.values()[0]
            status = ":hourglass: %s is deploying" % deploy.who
        else:  # > 1
            status = ":hourglass: %d deploys in progress" % deploy_count

        new_topic = " | ".join((
            status,
            "%s has the :shell:" % (self.queue[0] if self.queue else "no one"),
            "queue: %s" % (", ".join(self.queue[1:]) or "<empty>"),
        ))

        if new_topic != self.current_topic:
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
                                  '%s started deploy "%s" '
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
                                  """%s's deploy "%s" is %d%% complete.""" %
                                  (deploy.who, id, deploy.quadrant * 25))
        deploy.quadrant += 1

    def onPushEnded(self, id):
        who, duration = self._remove_deploy(id)

        if not who:
            return

        self.irc.bot.send_message(
            self.config.channel,
            """%s's deploy "%s" complete. """
            "Took %s." % (who, id, pretty_and_accurate_time_span(duration))
        )
        self._update_topic()

    def onPushError(self, id, error):
        deploy = self.deploys.get(id)
        if not deploy:
            return

        deploy.expirator.delay(self.config.deploy_ttl)
        self.irc.bot.send_message(self.config.channel,
                                  ("""%s's deploy "%s" encountered """
                                   "an error: %s") %
                                  (deploy.who, id, error))

    def onPushAborted(self, id, reason):
        who, duration = self._remove_deploy(id)

        if not who:
            return

        self.irc.bot.send_message(self.config.channel,
                                  """%s's deploy "%s" aborted (%s)""" %
                                  (who, id, reason))
        self._update_topic()


def make_plugin(config, http, irc):
    deploy_config = DeployConfig(config)
    monitor = DeployMonitor(deploy_config, irc)

    # yay channels
    irc.channels.add(deploy_config.channel)

    # set up http api
    deploy_root = resource.Resource()
    http.root.putChild('deploy', deploy_root)
    deploy_root.putChild('begin', DeployBeganListener(http, monitor))
    deploy_root.putChild('end', DeployEndedListener(http, monitor))
    deploy_root.putChild('abort', DeployAbortedListener(http, monitor))
    deploy_root.putChild('error', DeployErrorListener(http, monitor))
    deploy_root.putChild('progress', DeployProgressListener(http, monitor))

    # register our irc commands
    irc.register_command(monitor.status)
    irc.register_command(monitor.hold)
    irc.register_command(monitor.unhold)
    irc.register_command(monitor.acquire)
    irc.register_command(monitor.release)
    irc.register_command(monitor.jump)
    irc.register_command(monitor.kick)
