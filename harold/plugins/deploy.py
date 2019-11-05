import datetime
from enum import Enum
import functools
import hashlib
import hmac
import json
import pytz
import re
import time

from twisted.web import resource, server
from twisted.internet import reactor, task
from twisted.internet.defer import inlineCallbacks, returnValue

from harold.conf import PluginConfig, Option, tup
from harold.plugins.http import ProtectedResource
from harold.plugins.salons import WouldOrphanRepositoriesError
from harold.utils import (
    constant_time_compare,
    dehilight,
    fmt_time,
    parse_time,
    pretty_and_accurate_time_span,
    timerange_overlap,
    utc_offset,
)


# how old/new a deploy status request's timestamp can be to be allowed
MAX_SKEW_SECONDS = 60

# how long in seconds before we consider a deploy broken and remove it
DEPLOY_TTL = 3600

# how long in seconds before we warn the user their conch is about to expire
CONCH_TTL = 60*55

# how long in seconds they have to respond before we actually expire it
CONCH_GRACE = 60*5


class DeployConfig(PluginConfig):
    organizations = Option(tup)
    default_hours_start = Option(parse_time)
    default_hours_end = Option(parse_time)
    default_tz = Option(pytz.timezone)
    blackout_hours_start = Option(parse_time)
    blackout_hours_end = Option(parse_time)


class DeployHoldType(Enum):
    code_freeze = 'Code Freeze'
    manual = 'Manual'


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

        salon_name = request.args["salon"][0]
        salons_deferred = self.monitor.salons.by_name(salon_name)

        def send_response(salon):
            request.setHeader("Content-Type", "application/json")
            request.write(json.dumps({
                "time_status": salon.current_time_status(),
                "busy": bool(salon.deploys),
                "hold": salon.current_hold,
            }))
            request.finish()
        salons_deferred.addCallback(send_response)

        return server.NOT_DONE_YET


class DeployBeganListener(DeployListener):
    isLeaf = True

    def _handle_request(self, request):
        salon = request.args["salon"][0]
        id = unicode(request.args['id'][0], 'utf-8')
        who = request.args['who'][0]
        args = request.args['args'][0]
        log_path = unicode(request.args['log_path'][0], 'utf-8')
        count = int(request.args['count'][0])
        self.monitor.onPushBegan(salon, id, who, args, log_path, count)


class DeployEndedListener(DeployListener):
    isLeaf = True

    def _handle_request(self, request):
        salon = request.args["salon"][0]
        id = unicode(request.args['id'][0], 'utf-8')

        try:
            failed_hosts_arg = request.args["failed_hosts"][0]
        except KeyError:
            failed_hosts = []
        else:
            failed_hosts = filter(None, failed_hosts_arg.decode("utf-8").split(","))

        self.monitor.onPushEnded(salon, id, failed_hosts)


class DeployErrorListener(DeployListener):
    isLeaf = True

    def _handle_request(self, request):
        salon = request.args["salon"][0]
        id = unicode(request.args['id'][0], 'utf-8')
        error = request.args['error'][0]
        self.monitor.onPushError(salon, id, error)


class DeployAbortedListener(DeployListener):
    isLeaf = True

    def _handle_request(self, request):
        salon = request.args["salon"][0]
        id = unicode(request.args['id'][0], 'utf-8')
        reason = request.args['reason'][0]
        self.monitor.onPushAborted(salon, id, reason)


class DeployProgressListener(DeployListener):
    isLeaf = True

    def _handle_request(self, request):
        salon = request.args["salon"][0]
        id = unicode(request.args['id'][0], 'utf-8')
        host = request.args['host'][0]
        index = float(request.args['index'][0])
        self.monitor.onPushProgress(salon, id, host, index)


class DeployHoldListener(DeployListener):
    """
    Trigger a deploy hold for specific salon
    """
    isLeaf = True

    def _handle_request(self, request):
        reason = request.args['reason'][0]
        salon_name = request.args['salon'][0]
        channel = '#' + salon_name
        self.monitor.hold(self.monitor.irc.bot, None, channel, reason)

class DeployUnHoldListener(DeployListener):
    """
    Remove a deploy hold on a specific salon
    """
    isLeaf = True

    def _handle_request(self, request):
        salon_name = request.args['salon'][0]
        channel = '#' + salon_name
        self.monitor.unhold(self.monitor.irc.bot, None, channel)

class DeployHoldAllListener(DeployListener):
    """
    Trigger a deploy hold for all salons
    """
    isLeaf = True

    def _handle_request(self, request):
        reason = request.args['reason'][0]
        self.monitor.hold_all(self.monitor.irc.bot, None, None, reason)


class DeployUnholdAllListener(DeployListener):
    """
    Remove a deploy hold for all salons
    """
    isLeaf = True

    def _handle_request(self, request):
        self.monitor.unhold_all(self.monitor.irc.bot, None, None)


class DeployGetSalonNamesListener(DeployListener):
    isLeaf = True

    def _handle_request(self, request):

        def send_response(salons):
            salon_names = [salon.name for salon in salons]

            # Configure the response
            request.setHeader("Content-Type", "application/json")
            request.write(json.dumps(salon_names))
            request.finish()

        # The 'all' method returns a Twisted Deferred object.
        # So we have to handle this request in an asynchronous
        # manner by adding a callback to handle the asynchronous
        # execution.
        salons_deferred = self.monitor.salons.all()
        salons_deferred.addCallback(send_response)

        return server.NOT_DONE_YET


class DeploySendAnnouncementListener(DeployListener):
    """
    Send an announcement message to ALL code salons
    """
    isLeaf = True

    def _handle_request(self, request):
        message = request.args['message'][0]
        self.monitor.announce(self.monitor.irc.bot, 'harold', None, message)


class OngoingDeploy(object):
    pass


class Salon(object):
    def __init__(self, db, config):
        self.db = db
        self.name = config.name
        self.channel = config.channel
        self.allow_deploys = config.allow_deploys
        self.conch_emoji = config.conch_emoji.encode("utf-8")
        self.deploy_hours_start = config.deploy_hours_start
        self.deploy_hours_end = config.deploy_hours_end
        self.tz = config.tz
        self.deploys = {}
        self.current_hold = None
        self.current_hold_type = None
        self.previous_freeze = None
        self.current_conch = ""
        self.queue = []
        self.current_topic = self._make_topic()
        self.conch_lease = None

    def _make_topic(self):
        deploy_count = len(self.deploys)

        if self.current_hold is not None:
            if self.current_hold_type == DeployHoldType.code_freeze:
                status = ":snowflake: CODE FREEZE -- No deploys (%s)" % self.current_hold
            else:
                status = ":no_entry_sign: deploys ON HOLD (%s)" % self.current_hold
        else:
            time_status = self.current_time_status()

            if time_status == "work_time":
                status = ":office: working hours, normal deploy rules apply"
            elif time_status == "cleanup_time":
                status = ":hmm: it's late, please be mindful"
            else:
                status = ":warning: after hours, emergency deploys only"

        if deploy_count == 0:
            deploy_status = "no active deploys"
        elif deploy_count == 1:
            deploy = self.deploys.values()[0]
            deploy_status = "%s is deploying" % deploy.who
        else:  # > 1
            deploy_status = "%d deploys in progress" % deploy_count

        return " | ".join((
            status,
            "%s has the %s" % ("@" + self.queue[0] if self.queue else "no one", self.conch_emoji),
            deploy_status,
            "queue: %s" % (", ".join(map(dehilight, self.queue[1:])) or "<empty>"),
        ))

    def update_topic(self, irc, force=False):
        if not self.allow_deploys:
            return

        new_topic = self._make_topic()
        if force or new_topic != self.current_topic:
            irc.set_topic(self.channel, new_topic)
            self.current_topic = new_topic

    def update_conch(self, irc):
        if self.queue:
            new_conch = self.queue[0]
            if new_conch != self.current_conch:
                is_work_hours = self.current_time_status() in ("work_time", "cleanup_time")

                if self.current_hold is not None:
                    irc.send_message(self.channel, "@%s: you have the %s (but deploys are on hold)" % (new_conch, self.conch_emoji))
                elif not is_work_hours:
                    irc.send_message(self.channel, "@%s: you have the %s (but it's after hours)" % (new_conch, self.conch_emoji))
                else:
                    irc.send_message(self.channel, "@%s: you have the %s" % (new_conch, self.conch_emoji))

                if len(self.queue) > 1:
                    irc.send_message(self.channel, "@%s: you're up next. please get ready!" % self.queue[1])

                self.reset_conch_lease(irc, new_conch)
        else:
            new_conch = None

        if new_conch is None:
            self.reset_conch_lease(irc, None)

        self.current_conch = new_conch

    def reset_conch_lease(self, irc, new_holder):
        if self.conch_lease and self.conch_lease.active():
            self.conch_lease.cancel()

        if new_holder:
            self.conch_lease = reactor.callLater(CONCH_TTL, self.warn_conch_lease_expiration, irc)

    def warn_conch_lease_expiration(self, irc):
        if self.current_conch:
            if self.deploys:
                irc.send_message(self.channel, "automatically extending your time with the %s since a deploy is ongoing" % (self.conch_emoji,))
                self.conch_lease = reactor.callLater(CONCH_GRACE, self.warn_conch_lease_expiration, irc)
                return

            irc.send_message(self.channel, "@%s: your time with the %s expires in 5 minutes. if you still need it, say `harold acquire`" % (self.current_conch, self.conch_emoji))
            self.conch_lease = reactor.callLater(CONCH_GRACE, self.expire_conch, irc)

    def expire_conch(self, irc):
        if self.current_conch:
            irc.send_message(self.channel, "@%s: your time with the %s has reached an end" % (self.current_conch, self.conch_emoji))
            self.queue.remove(self.current_conch)
            self.conch_lease = None

            self.update_conch(irc)
            self.update_topic(irc)

    def hold(self, irc, type, reason):
        """
        Sets a deploy hold status on a salon

        :param irc: IrcPlugin object for sending IRC messages
        :param type: DeployHoldType enum
        :param reason: Reason text

        :return: None
        """
        if not reason:
            reason_text = "no reason given"
        else:
            reason_text = " ".join(reason)

        # If the type is a manual hold and we are currently in a
        # code freeze then there is likely some emergency that
        # needs to be addressed.  However, once that hold has been
        # lifted we wish to restore the previous freeze.  Thus we
        # need to preserve the freeze reason for restoration.
        if type == DeployHoldType.manual and self.current_hold_type == DeployHoldType.code_freeze:
            self.previous_freeze = self.current_hold

        self.current_hold = reason_text
        self.current_hold_type = type
        self.update_topic(irc)

    def unhold(self, irc):
        current_hold = None
        current_hold_type = None

        # If there was a freeze that had been preserved due to a
        # manual hold being placed during the freeze, we should
        # restore that.  Otherwise, simply lift the hold.
        if self.previous_freeze:
            current_hold_type = DeployHoldType.code_freeze
            current_hold = self.previous_freeze

        self.current_hold = current_hold
        self.current_hold_type = current_hold_type
        self.update_topic(irc)
        self.previous_freeze = None

    def remove_deploy(self, id):
        deploy = self.deploys.get(id)
        if not deploy:
            return None, None

        if deploy.expirator.active():
            deploy.expirator.cancel()

        del self.deploys[id]
        return deploy.who, datetime.datetime.now() - deploy.when

    @inlineCallbacks
    def all_repos(self):
        repos = yield self.db.get_salon_repositories(self.name)
        returnValue(repos)

    @inlineCallbacks
    def add_repo(self, repo_name):
        yield self.db.add_repository(self.name, repo_name)

    @inlineCallbacks
    def remove_repo(self, repo_name):
        yield self.db.remove_repository(self.name, repo_name)

    @inlineCallbacks
    def set_deploy_hours(self, irc, start, end, tz):
        yield self.db.set_deploy_hours(self.name, start, end, tz)
        self.deploy_hours_start = start
        self.deploy_hours_end = end
        self.tz = tz
        self.update_topic(irc)

    def current_time_status(self):
        now = datetime.datetime.now(tz=self.tz)
        date = now.date()
        time = now.time()

        end_datetime = datetime.datetime.combine(date, self.deploy_hours_end)
        cleanup = (end_datetime - datetime.timedelta(hours=1)).time()

        if time < self.deploy_hours_start:
            return "after_hours"

        if date.weekday() in (0, 1, 2, 3):
            # monday through thursday, 1 hour before end
            if time < cleanup:
                return "work_time"
            elif time < self.deploy_hours_end:
                return "cleanup_time"
            else:
                return "after_hours"
        else:
            # no work on the weekend
            return "after_hours"


class SalonManager(object):
    def __init__(self, salon_config_db):
        self.salon_config_db = salon_config_db
        self.salons = {}

        looper = task.LoopingCall(self._write_status)
        looper.start(10)

    @inlineCallbacks
    def all(self):
        salon_configs = yield self.salon_config_db.get_salons()
        for salon_config in salon_configs:
            if "#" + salon_config.name not in self.salons:
                self.salons["#" + salon_config.name] = Salon(
                    self.salon_config_db,
                    salon_config,
                )
        returnValue(self.salons.values())

    @inlineCallbacks
    def by_channel(self, channel_name):
        yield self.all()
        returnValue(self.salons.get(channel_name))

    @inlineCallbacks
    def by_name(self, name):
        salon = yield self.by_channel(u"#" + name)
        returnValue(salon)

    @inlineCallbacks
    def by_repository(self, name):
        repo = yield self.salon_config_db.get_repository(name)
        if not repo:
            returnValue(None)

        salon = yield self.by_channel(repo.channel)
        returnValue(salon)

    @inlineCallbacks
    def create(self, channel_name, emoji, deploy_hours_start, deploy_hours_end, tz):
        config = yield self.salon_config_db.create_salon(
            channel_name.lstrip("#"),
            emoji,
            deploy_hours_start,
            deploy_hours_end,
            tz,
        )
        new_salon = Salon(self.salon_config_db, config)
        self.salons[channel_name] = new_salon
        returnValue(new_salon)

    @inlineCallbacks
    def destroy(self, channel_name):
        yield self.salon_config_db.delete_salon(channel_name.lstrip("#"))
        del self.salons[channel_name]

    def _write_status(self):
        data = []

        for salon in self.salons.itervalues():
            data.append({
                "name": salon.name,
                "allow_deploys": bool(salon.allow_deploys),
                "deploy_hours_start": salon.deploy_hours_start.isoformat(),
                "deploy_hours_end": salon.deploy_hours_end.isoformat(),
                "timezone": str(salon.tz),
                "deploys": [
                    {
                        "user": d.who,
                        "completion": float(d.completion) / d.host_count,
                    } for d in salon.deploys
                ],
                "hold": salon.current_hold,
                "queue": salon.queue,
                "status": salon.current_time_status(),
            })

        with open("/var/lib/harold/salons.json", "w") as f:
            json.dump(data, f)


class DeployMonitor(object):
    def __init__(self, config, irc, salons):
        self.config = config
        self.irc = irc
        self.salons = SalonManager(salons)

        looper = task.LoopingCall(self._update_topics)
        looper.start(10)

    @inlineCallbacks
    def _update_topics(self):
        salons = yield self.salons.all()
        for salon in salons:
            salon.update_topic(self.irc.bot)

    @inlineCallbacks
    def salonify(self, irc, sender, channel, *args):
        if not args:
            irc.send_message(channel, "USAGE: salonify :emoji_name:")
            return
        emoji = args[0]

        salon = yield self.salons.by_channel(channel)
        if salon:
            irc.send_message(channel, "This channel is already a salon!")
            return

        if not channel.endswith("-salon"):
            irc.send_message(channel, "Salon channel names should end with -salon")
            return

        if not re.match("^:[^:]+:$", emoji):
            irc.send_message(channel, "That doesn't look like a valid emoji.")
            return

        new_salon = yield self.salons.create(
            channel,
            emoji,
            self.config.default_hours_start,
            self.config.default_hours_end,
            self.config.default_tz
        )
        new_salon.update_topic(irc, force=True)

    @inlineCallbacks
    def desalonify(self, irc, sender, channel, *ignored):
        salon = yield self.salons.by_channel(channel)
        if not salon:
            return

        try:
            yield self.salons.destroy(channel)
            irc.set_topic(channel, "This channel is no longer a salon.")
        except WouldOrphanRepositoriesError:
            irc.send_message(channel, "Desalonifying this room would orphan "
                             "repositories. Please use the 'repository' "
                             "command to rehome them first.")

    @inlineCallbacks
    def set_deploy_hours(self, irc, sender, channel, *args):
        def usage():
            irc.send_message(channel, "*USAGE:* set_deploy_hours 0900 1700 America/Los_Angeles")
            irc.send_message(channel, "List of timezone names: https://en.wikipedia.org/wiki/List_of_tz_database_time_zones#List")

        if not args or len(args) != 3:
            usage()
        start, end, tz_name = args

        salon = yield self.salons.by_channel(channel)
        if not salon:
            irc.send_message(channel, "This channel isn't a salon.")
            return

        try:
            tz = pytz.timezone(tz_name)
        except pytz.UnknownTimeZoneError:
            irc.send_message(channel, "*Error:* Unknown timezone {}".format(tz_name))
            usage()
            return

        try:
            start_time = parse_time(start)
            end_time = parse_time(end)
            if start_time > end_time:
                raise ValueError
        except ValueError:
            irc.send_message(channel, "*Error:* Invalid time range {} {}".format(start, end))
            usage()
            return

        date = datetime.datetime.now(tz=tz).date()
        deploy_start = tz.localize(datetime.datetime.combine(date, start_time))
        deploy_end = tz.localize(datetime.datetime.combine(date, end_time))
        deploy_timerange = (deploy_start, deploy_end)

        blackout_tz = self.config.default_tz
        blackout_date = datetime.datetime.now(tz=blackout_tz).date()
        blackout_start = blackout_tz.localize(datetime.datetime.combine(blackout_date, self.config.blackout_hours_start))
        blackout_end = blackout_tz.localize(datetime.datetime.combine(blackout_date, self.config.blackout_hours_end))

        # User-defined deploy hours can only exist in a single day in their
        # given timezone, but may cross day boundaries in the blackout
        # timezone. This necessitates us checking for overlap for both today
        # and yesterday.
        # Example: Deploy hours of 0100-0200 EST, blackout hours of 2200-2300 PST.
        for i in (0, 1):
            delta = datetime.timedelta(days=i)
            blackout_timerange = (blackout_start - delta, blackout_end - delta)

            if timerange_overlap(deploy_timerange, blackout_timerange):
                irc.send_message(channel, "ERROR: Requested deploy hours overlap with blackout window.")
                irc.send_message(channel, "Blackout hours are {} to {}, {} ({})".format(
                    fmt_time(blackout_start.astimezone(tz)),
                    fmt_time(blackout_end.astimezone(tz)),
                    tz,
                    utc_offset(tz),
                ))
                return

        yield salon.set_deploy_hours(irc, start_time, end_time, tz)
        irc.send_message(salon.channel,
                         """deploy hours set to %s-%s, %s (%s)""" %
                         (start, end, tz_name, utc_offset(salon.tz)))


    @inlineCallbacks
    def get_deploy_hours(self, irc, sender, channel):
        "Get the deploy hours for this salon."
        salon = yield self.salons.by_channel(channel)
        if not salon:
            irc.send_message(channel, "This channel isn't a salon.")
            return

        start = fmt_time(salon.deploy_hours_start)
        end = fmt_time(salon.deploy_hours_end)
        tz = salon.tz
        irc.send_message(salon.channel,
                                  """deploy hours are %s-%s, %s (%s)""" %
                                  (start, end, tz, utc_offset(tz)))

    @inlineCallbacks
    def repository(self, irc, sender, channel, subcommand, *args):
        def validate_repo_name(repo_name):
            org, sep, repo = repo_name.partition("/")
            if sep != "/":
                irc.send_message(channel, "You must specify a full repository "
                                 "name with organization (like "
                                 "reddit/error-pages).")
                returnValue(None)
            elif org not in self.config.organizations:
                irc.send_message(channel, "I can only watch repositories in "
                                 "one of the following organizations: " +
                                 ", ".join(self.config.organizations))
                returnValue(None)

        if subcommand == "where":
            repo_name = args[0]

            validate_repo_name(repo_name)
            salon = yield self.salons.by_repository(repo_name)

            if salon:
                irc.send_message(channel, "%s is managed in %s" % (repo_name, salon.channel))
            else:
                irc.send_message(channel, "%s is not managed in any salon" % (repo_name,))

            returnValue(None)

        salon = yield self.salons.by_channel(channel)
        if not salon:
            return

        all_repos = yield salon.all_repos()
        all_repo_names = [r.name for r in all_repos]

        if subcommand == "list":
            if all_repo_names:
                chunks = ["This salon manages: "]

                # determined empirically for slack :(
                MAX_IRC_MESSAGE_LENGTH = 340

                for repo in sorted(all_repo_names):
                    length = sum(len(chunk)+2 for chunk in chunks)
                    if length + len(repo) > MAX_IRC_MESSAGE_LENGTH:
                        irc.send_message(channel, chunks[0] + ", ".join(chunks[1:]))
                        chunks = ["and "]

                    chunks.append(repo)

                if chunks:
                    irc.send_message(channel, chunks[0] + ", ".join(chunks[1:]))
            else:
                irc.send_message(channel, "This salon manages no repositories")
        elif subcommand == "add":
            repo_name = args[0]
            validate_repo_name(repo_name)

            if repo_name not in all_repo_names:
                salon.add_repo(repo_name)
                irc.send_message(channel, "This salon will now watch `%s`" % repo_name)
            else:
                irc.send_message(channel, "This salon is already watching `%s`" % repo_name)
        elif subcommand == "remove":
            repo_name = args[0]
            all_repo_names_lower = [n.lower() for n in all_repo_names]

            if repo_name.lower() in all_repo_names_lower:
                salon.remove_repo(repo_name)
                irc.send_message(channel, "This salon will no longer watch `%s`" % repo_name)
            else:
                irc.send_message(channel, "This salon is not watching `%s`" % repo_name)
        else:
            irc.send_message(channel, "Unknown repository command.")

    @inlineCallbacks
    def help(self, irc, sender, channel, *args):
        salon = yield self.salons.by_channel(channel)
        if not salon:
            return

        irc.send_message(channel, "see: https://github.com/spladug/harold/wiki")

    @inlineCallbacks
    def status(self, irc, sender, channel):
        "Get the status of currently running deploys."
        salon = yield self.salons.by_channel(channel)
        if not (salon and salon.allow_deploys):
            return

        reply = functools.partial(self.irc.bot.send_message, channel)

        if not salon.deploys:
            reply("@%s: there are currently no active deploys." % sender)

        deploys = sorted(salon.deploys.values(), key=lambda d: d.when)
        for d in deploys:
            status = ""
            if d.where:
                percent = (float(d.completion) / d.host_count) * 100.0
                status = " (which is on %s -- %d%% done)" % (d.where, percent)

            reply('@%s: %s started deploy "%s"%s at %s with args "%s". log: %s' %
                  (sender, d.who, d.id, status, d.when.strftime("%H:%M"),
                   d.args, d.log_path))

    def status_all(self, irc, sender, channel):
        irc.send_message(channel, "status_all is now on the salon dashboard")

    @inlineCallbacks
    def hold(self, irc, sender, channel, *reason):
        salon = yield self.salons.by_channel(channel)
        if not (salon and salon.allow_deploys):
            return

        type = DeployHoldType.manual
        # 'reason' is the reason string broken down as a tuple of words
        if 'freeze' in ' '.join(reason).lower():
            type = DeployHoldType.code_freeze

        salon.hold(irc, type, reason)

    @inlineCallbacks
    def hold_all(self, irc, sender, channel, *reason):
        salons = yield self.salons.all()

        type = DeployHoldType.manual
        # 'reason' is the reason string broken down as a tuple of words
        if 'freeze' in ' '.join(reason).lower():
            type = DeployHoldType.code_freeze

        for salon in salons:
            salon.hold(irc, type, reason)

    @inlineCallbacks
    def unhold(self, irc, sender, channel, *ignored):
        salon = yield self.salons.by_channel(channel)
        if not (salon and salon.allow_deploys):
            return
        salon.unhold(irc)

    @inlineCallbacks
    def unhold_all(self, irc, sender, channel, *ignored):
        salons = yield self.salons.all()
        for salon in salons:
            salon.unhold(irc)

    @inlineCallbacks
    def acquire(self, irc, sender, channel, *ignored):
        salon = yield self.salons.by_channel(channel)
        if not (salon and salon.allow_deploys):
            return

        if sender in salon.queue:
            if salon.current_conch == sender:
                salon.reset_conch_lease(irc, sender)
                irc.send_message(channel, "@%s: your time with the %s has been extended" % (sender, salon.conch_emoji))
            else:
                irc.send_message(channel, "@%s: you are already in the queue" % sender)
            return

        if salon.queue:
            conch_holder = salon.queue[0]

            if len(salon.queue) > 1:
                irc.send_message(channel, "@%s: ok -- you're in the queue. (@%s still has the %s)" % (sender, conch_holder, salon.conch_emoji))
            else:
                irc.send_message(channel, "@%s: ok -- you're in the queue and you're next so please be ready! (@%s still has the %s)" % (sender, conch_holder, salon.conch_emoji))

        salon.queue.append(sender)
        salon.update_topic(irc)
        salon.update_conch(irc)

    @inlineCallbacks
    def release(self, irc, sender, channel, *ignored):
        salon = yield self.salons.by_channel(channel)
        if not (salon and salon.allow_deploys):
            return

        if sender not in salon.queue:
            irc.send_message(channel, "@%s: you are not in the queue" % sender)
            return

        salon.queue.remove(sender)
        salon.update_conch(irc)
        salon.update_topic(irc)

    @inlineCallbacks
    def jump(self, irc, sender, channel):
        salon = yield self.salons.by_channel(channel)
        if not (salon and salon.allow_deploys):
            return

        if salon.queue and salon.queue[0] == sender:
            irc.send_message(channel, "@%s: you already have the %s" % (sender, salon.conch_emoji))
            return

        if sender in salon.queue:
            salon.queue.remove(sender)
        salon.queue.insert(0, sender)
        salon.update_conch(irc)
        salon.update_topic(irc)

    @inlineCallbacks
    def notready(self, irc, sender, channel, *args):
        salon = yield self.salons.by_channel(channel)
        if not (salon and salon.allow_deploys):
            return

        try:
            old_pos = salon.queue.index(sender)
        except ValueError:
            irc.send_message(channel, "@%s: you are not in the queue" % (sender,))
            returnValue(None)

        new_pos = old_pos + 1
        if new_pos == len(salon.queue):
            irc.send_message(channel, "@%s: no one is behind you in the queue, no rush" % (sender,))
            returnValue(None)

        salon.queue[new_pos], salon.queue[old_pos] = salon.queue[old_pos], salon.queue[new_pos]
        salon.update_conch(irc)
        salon.update_topic(irc)

    @inlineCallbacks
    def enqueue(self, irc, sender, channel, *users):
        salon = yield self.salons.by_channel(channel)
        if not (salon and salon.allow_deploys):
            return

        for user in users:
            if user not in salon.queue:
                salon.queue.append(user)

        salon.update_topic(irc)
        salon.update_conch(irc)

    @inlineCallbacks
    def kick(self, irc, sender, channel, user):
        salon = yield self.salons.by_channel(channel)
        if not (salon and salon.allow_deploys):
            return

        if user not in salon.queue:
            irc.send_message(channel, "@%s: %s is not in the queue" % (sender, dehilight(user)))
            return

        salon.queue.remove(user)
        salon.update_conch(irc)
        salon.update_topic(irc)

        if user == sender:
            irc.send_message(channel, ":nelson: stop kicking yourself! stop kicking yourself!")

    @inlineCallbacks
    def refresh(self, irc, sender, channel):
        salon = yield self.salons.by_channel(channel)
        if not (salon and salon.allow_deploys):
            return
        salon.update_topic(irc, force=True)

    @inlineCallbacks
    def refresh_all(self, irc, sender, channel):
        salons = yield self.salons.all()
        for salon in salons:
            salon.update_topic(irc, force=True)

    @inlineCallbacks
    def onPushBegan(self, salon_name, id, who, args, log_path, count):
        salon = yield self.salons.by_name(salon_name)
        if not salon:
            return

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
        deploy.expirator = reactor.callLater(DEPLOY_TTL, salon.remove_deploy, id)

        salon.deploys[id] = deploy
        salon.update_topic(self.irc.bot)

        self.irc.bot.send_message(salon.channel,
                                  '@%s started deploy "%s" '
                                  "with args %s" % (who, id, args))

    @inlineCallbacks
    def onPushProgress(self, salon_name, id, host, index):
        salon = yield self.salons.by_name(salon_name)
        if not salon:
            return

        deploy = salon.deploys.get(id)
        if not deploy:
            return

        deploy.expirator.delay(DEPLOY_TTL)
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

        self.irc.bot.send_message(salon.channel,
                                  """deploy "%s" by @%s is %d%% complete.""" %
                                  (id, deploy.who, deploy.quadrant * 25))
        deploy.quadrant += 1

    @inlineCallbacks
    def onPushEnded(self, salon_name, id, failed_hosts):
        salon = yield self.salons.by_name(salon_name)
        if not salon:
            return

        deploy = salon.deploys.get(id)
        who, duration = salon.remove_deploy(id)

        if not who:
            return

        self.irc.bot.send_message(
            salon.channel,
            """deploy "%s" by @%s is complete. """
            "Took %s." % (id, who, pretty_and_accurate_time_span(duration))
        )
        salon.update_topic(self.irc.bot)

        if failed_hosts:
            self.irc.bot.send_message(
                "#monitoring",
                "Deploy `%s` in %s encountered errors on the "
                    "following hosts: %s. See %s for more information." % (
                        id, salon.channel, ", ".join(sorted(failed_hosts)),
                        deploy.log_path)
            )

    @inlineCallbacks
    def onPushError(self, salon_name, id, error):
        salon = yield self.salons.by_name(salon_name)
        if not salon:
            return

        deploy = salon.deploys.get(id)
        if not deploy:
            return

        deploy.expirator.delay(DEPLOY_TTL)
        self.irc.bot.send_message(salon.channel,
                                  ("""deploy "%s" by @%s encountered """
                                   "an error: %s") %
                                  (id, deploy.who, error))

    @inlineCallbacks
    def onPushAborted(self, salon_name, id, reason):
        salon = yield self.salons.by_name(salon_name)
        if not salon:
            return

        who, duration = salon.remove_deploy(id)

        if not who:
            return

        self.irc.bot.send_message(salon.channel,
                                  """deploy "%s" by @%s aborted (%s)""" %
                                  (id, who, reason))
        salon.update_topic(self.irc.bot)

    @inlineCallbacks
    def forget(self, irc, sender, channel, deploy_id, *ignored):
        salon = yield self.salons.by_channel(channel)
        if not salon:
            return

        who, duration = salon.remove_deploy(deploy_id)

        if not who:
            return

        irc.send_message(
            salon.channel, "%s doesn't look like anything to me" % deploy_id)
        salon.update_topic(irc)

    @inlineCallbacks
    def announce(self, irc, sender, channel, *message):
        message = " ".join(message)
        salons = yield self.salons.all()

        for salon in salons:
            irc.send_message(salon.channel, ":siren: ANNOUNCEMENT FROM @%s: %s" % (
                sender, message))


def make_plugin(config, http, irc, salons):
    deploy_config = DeployConfig(config)
    monitor = DeployMonitor(deploy_config, irc, salons)

    # set up http api
    deploy_root = resource.Resource()
    http.root.putChild('deploy', deploy_root)
    deploy_root.putChild('status', DeployStatusListener(http.hmac_secret, monitor))
    deploy_root.putChild('begin', DeployBeganListener(http, monitor))
    deploy_root.putChild('end', DeployEndedListener(http, monitor))
    deploy_root.putChild('abort', DeployAbortedListener(http, monitor))
    deploy_root.putChild('error', DeployErrorListener(http, monitor))
    deploy_root.putChild('progress', DeployProgressListener(http, monitor))
    deploy_root.putChild('hold', DeployHoldListener(http, monitor))
    deploy_root.putChild('unhold', DeployUnHoldListener(http, monitor))
    deploy_root.putChild('hold_all', DeployHoldAllListener(http, monitor))
    deploy_root.putChild('unhold_all', DeployUnholdAllListener(http, monitor))
    deploy_root.putChild('send_announcement', DeploySendAnnouncementListener(http, monitor))
    deploy_root.putChild('get_salon_names', DeployGetSalonNamesListener(http, monitor))

    # register our irc commands
    irc.register_command(monitor.salonify)
    irc.register_command(monitor.desalonify)
    irc.register_command(monitor.repository)
    irc.register_command(monitor.help)
    irc.register_command(monitor.status)
    irc.register_command(monitor.status_all)
    irc.register_command(monitor.hold)
    irc.register_command(monitor.unhold)
    irc.register_command(monitor.hold_all)
    irc.register_command(monitor.unhold_all)
    irc.register_command(monitor.acquire)
    irc.register_command(monitor.release)
    irc.register_command(monitor.jump)
    irc.register_command(monitor.notready)
    irc.register_command(monitor.enqueue)
    irc.register_command(monitor.kick)
    irc.register_command(monitor.refresh)
    irc.register_command(monitor.refresh_all)
    irc.register_command(monitor.forget)
    irc.register_command(monitor.announce)
    irc.register_command(monitor.set_deploy_hours)
    irc.register_command(monitor.get_deploy_hours)
