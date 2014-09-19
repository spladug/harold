import datetime
import functools

from twisted.web import resource
from twisted.internet import reactor

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
        self.topic_to_restore = None
        self.irc.topicUpdated += self._topic_changed

    def status(self, irc, sender, channel):
        "Get the status of currently running deploys."
        if channel != self.config.channel:
            return

        reply = functools.partial(self.irc.bot.send_message, channel)
        sender_nick = sender.partition('!')[0]

        if not self.deploys:
            reply("%s, there are currently no active pushes." % sender_nick)

        deploys = sorted(self.deploys.values(), key=lambda d: d.when)
        for d in deploys:
            status = ""
            if d.where:
                percent = (float(d.completion) / d.host_count) * 100.0
                status = " (which is on %s -- %d%% done)" % (d.where, percent)

            reply('%s, %s started push "%s"%s at %s with args "%s". log: %s' %
                  (sender_nick, d.who, d.id, status, d.when.strftime("%H:%M"),
                   d.args, d.log_path))

    def _topic_changed(self, user, channel, topic):
        if channel != self.config.channel:
            return

        if topic.startswith("<%s>" % self.irc.config.nick):
            return

        self.topic_to_restore = topic

    def _update_topic(self):
        nick = self.irc.config.nick
        deploy_count = len(self.deploys)

        if deploy_count == 0:
            if self.topic_to_restore:
                topic = self.topic_to_restore
            else:
                topic = "no active pushes - alert word: mayday mayday mayday"
        elif deploy_count == 1:
            deploy = self.deploys.values()[0]
            topic = ("<%s> %s started push at "
                     "%s with args: %s" %
                     (nick, deploy.who, deploy.when.strftime("%H:%M"),
                                            deploy.args))
        else:  # > 1
            earliest = min(d.when for d in self.deploys.itervalues())
            topic = ('<%s> %d pushes running (earliest '
                     'started at %s). check "status".' %
                     (nick, deploy_count, earliest.strftime("%H:%M")))

        self.irc.bot.set_topic(self.config.channel, topic)

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
                                  '%s started push "%s" '
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
                                  """%s's push "%s" is %d%% complete.""" %
                                  (deploy.who, id, deploy.quadrant * 25))
        deploy.quadrant += 1

    def onPushEnded(self, id):
        who, duration = self._remove_deploy(id)

        if not who:
            return

        self.irc.bot.send_message(
            self.config.channel,
            """%s's push "%s" complete. """
            "Took %s." % (who, id, pretty_and_accurate_time_span(duration))
        )
        self._update_topic()

    def onPushError(self, id, error):
        deploy = self.deploys.get(id)
        if not deploy:
            return

        deploy.expirator.delay(self.config.deploy_ttl)
        self.irc.bot.send_message(self.config.channel,
                                  ("""%s's push "%s" encountered """
                                   "an error: %s") %
                                  (deploy.who, id, error))

    def onPushAborted(self, id, reason):
        who, duration = self._remove_deploy(id)

        if not who:
            return

        self.irc.bot.send_message(self.config.channel,
                                  """%s's push "%s" aborted (%s)""" %
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
