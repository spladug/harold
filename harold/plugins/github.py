import collections
import datetime
import json
import re

from twisted.internet.defer import inlineCallbacks, returnValue

from harold.plugins.http import ProtectedResource
from harold.shorturl import UrlShortener
from harold.conf import PluginConfig, Option, tup
from harold.utils import dehilight


REPOSITORY_PREFIX = 'harold:repository:'

# https://github.com/reddit/reddit/pull/33#issuecomment-767815
_PULL_REQUEST_URL_RE = re.compile(r"""
https://github.com/
(?P<repository>[^/]+/[^/]+)
/pull/
(?P<number>\d+)
[#]issuecomment-\d+
""", re.VERBOSE)


def _parse_timestamp(ts):
    return datetime.datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")


_MENTION_RE = re.compile(r"@([A-Za-z0-9][A-Za-z0-9-]*)")
def _extract_reviewers(body):
    body = Salon.rewrite_emoji(body)
    reviewers = set()
    for line in body.splitlines():
        if ":eyeglasses:" in line:
            reviewers.update(_MENTION_RE.findall(line))
    return reviewers


class GitHubConfig(object):
    def __init__(self, config):
        self.repositories_by_name = {}
        self.channels = set()

        for section in config.parser.sections():
            if not section.startswith(REPOSITORY_PREFIX):
                continue

            repository = RepositoryConfig(config, section=section)
            repository.name = section[len(REPOSITORY_PREFIX):]
            self.repositories_by_name[repository.name] = repository
            self.channels.add(repository.channel)

        mappings = config.parser.items("harold:plugin:github")
        self.nicks_by_user = dict(mappings)

    def nick_by_user(self, user):
        return self.nicks_by_user.get(user.lower(), user)


class RepositoryConfig(PluginConfig):
    channel = Option(str)
    format = Option(str, '%(author)s committed %(commit_id)s (%(url)s) to ' +
                         '%(repository)s: %(summary)s')
    branches = Option(tup, [])
    max_commit_count = Option(int, default=3)
    bundled_format = Option(str, '%(authors)s made %(commit_count)d commits ' +
                                 '(%(commit_range)s - %(url)s) to ' +
                                 '%(repository)s')


def _get_commit_author(commit):
    "Return the author's github account or, if not present, full name."
    author_info = commit['author']
    return author_info.get('username', author_info['name'])


class PushDispatcher(object):
    def __init__(self, config, bot, shortener):
        self.config = config
        self.bot = bot
        self.shortener = shortener

    def _dispatch_commit(self, repository, branch, commit):
        d = self.shortener.make_short_url(commit['url'])

        def onUrlShortened(short_url):
            self.bot.send_message(repository.channel,
                                  repository.format % {
                'repository': repository.name,
                'branch': branch,

                'commit_id': commit['id'][:7],
                'url': short_url,
                'author': self.config.nick_by_user(_get_commit_author(commit)),
                'summary': commit['message'].splitlines()[0]
            })
        d.addCallback(onUrlShortened)

    def _dispatch_bundle(self, info, repository, branch, commits):
        authors = collections.Counter()
        for commit in commits:
            authors[self.config.nick_by_user(_get_commit_author(commit))] += 1
        before = info['before']
        after = info['after']
        commit_range = before[:7] + '..' + after[:7]
        url = "https://github.com/%s/compare/%s...%s" % (repository.name,
                                                         before,
                                                         after)

        d = self.shortener.make_short_url(url)

        def onUrlShortened(short_url):
            self.bot.send_message(repository.channel,
                                  repository.bundled_format % {
                'repository': repository.name,
                'branch': branch,
                'authors': ', '.join(a for a, c in authors.most_common()),
                'commit_count': len(commits),
                'commit_range': commit_range,
                'url': short_url,
            })
        d.addCallback(onUrlShortened)

    def _get_repository(self, parsed):
        repository_name = parsed["repository"]["full_name"]
        return self.config.repositories_by_name.get(repository_name)

    def dispatch_ping(self, parsed):
        repository = self._get_repository(parsed)
        if repository:
            self.bot.describe(
                repository.channel, "is now watching %s" % repository.name)

    def dispatch_push(self, parsed):
        repository = self._get_repository(parsed)
        if not repository:
            return
        branch = parsed['ref'].split('/')[-1]
        commits = parsed['commits']

        if not repository.branches or branch in repository.branches:
            if len(commits) <= repository.max_commit_count:
                for commit in commits:
                    self._dispatch_commit(repository, branch, commit)
            else:
                self._dispatch_bundle(parsed, repository, branch, commits)


class SalonDatabase(object):
    def __init__(self, database):
        self.database = database

    @inlineCallbacks
    def _insert(self, table, data, replace_on_conflict=False):
        if not self.database:
            return

        # this isn't as bad as it looks. just the table/column names are
        # done with string concatenation; those should be coming from
        # hard-coded strings in the source and therefore safe. actual data
        # is parameterized.
        query = (
            "INSERT %(conflict)s INTO %(table)s (%(columns)s) "
            "VALUES (%(placeholders)s);" % {
                "conflict": "OR REPLACE" if replace_on_conflict else "",
                "table": table,
                "columns": ", ".join(data.iterkeys()),
                "placeholders": ", ".join(":" + x for x in data.iterkeys()),
            }
        )
        yield self.database.runOperation(query, data)

    def _upsert(self, table, data):
        return self._insert(table, data, replace_on_conflict=True)

    @inlineCallbacks
    def _delete(self, table, data):
        if not self.database:
            return

        # this isn't as bad as it looks. just the table/column names are
        # done with string concatenation; those should be coming from
        # hard-coded strings in the source and therefore safe. actual data
        # is parameterized.
        query = (
            "DELETE FROM %(table)s WHERE %(conditions)s" % {
                "table": table,
                "conditions": " AND ".join("{0} = :{0}".format(column_name)
                                           for column_name in data.iterkeys()),
            }
        )
        yield self.database.runOperation(query, data)

    @inlineCallbacks
    def _is_author(self, repo, pr_id, username):
        if not self.database:
            return

        rows = yield self.database.runQuery(
            "SELECT COUNT(*) FROM github_pull_requests WHERE "
            "repository = :repository AND id = :id AND author = :username",
            {
                "repository": repo,
                "id": pr_id,
                "username": username,
            }
        )
        returnValue(bool(rows[0][0]))

    @inlineCallbacks
    def process_pullrequest(self, pull_request, repository):
        repo = repository or pull_request["repository"]["full_name"]
        id = int(pull_request["number"])

        timestamp = _parse_timestamp(pull_request["created_at"])
        yield self._upsert("github_pull_requests", {
            "repository": repo,
            "id": id,
            "created": timestamp,
            "author": pull_request["user"]["login"],
            "state": pull_request["state"],
            "title": pull_request["title"],
            "url": pull_request["html_url"],
        })
        yield self._add_mentions(repo, id, pull_request["body"], timestamp)

    @inlineCallbacks
    def update_review_state(self, repo, pr_id, body, timestamp, user, emoji):
        is_author = yield self._is_author(repo, pr_id, user)
        if is_author:
            yield self._add_mentions(repo, pr_id, body, timestamp)

        state = "unreviewed"
        if is_author and emoji == ":haircut:":
            state = "haircut"
        elif emoji == ":running:":
            state = "running"
        elif emoji == ":nail_care:":
            state = "nail_care"
        elif emoji == ":fish:":
            state = "fish"

        should_overwrite = (state != "unreviewed")

        try:
            yield self._insert("github_review_states", {
                "repository": repo,
                "pull_request_id": pr_id,
                "user": user,
                "timestamp": timestamp,
                "state": state,
            }, replace_on_conflict=should_overwrite)
        except self.database.module.IntegrityError:
            if should_overwrite:
                raise

    @inlineCallbacks
    def add_review_request(self, repo, pull_request_id, username, timestamp):
        try:
            yield self._insert("github_review_states", {
                "repository": repo,
                "pull_request_id": pull_request_id,
                "user": username,
                "timestamp": timestamp,
                "state": "unreviewed",
            })
        except self.database.module.IntegrityError:
            pass

    @inlineCallbacks
    def remove_review_request(self, repo, pull_request_id, username):
        yield self._delete("github_review_states", {
            "repository": repo,
            "pull_request_id": pull_request_id,
            "user": username,
        })

    @inlineCallbacks
    def _add_mentions(self, repo, id, body, timestamp):
        for mention in _extract_reviewers(body):
            yield self.add_review_request(repo, id, mention, timestamp)

    @inlineCallbacks
    def get_reviewers(self, repo, pr_id):
        if not self.database:
            returnValue([])

        rows = yield self.database.runQuery(
            "SELECT user FROM github_review_states WHERE "
            "repository = :repo AND pull_request_id = :prid AND "
            "state != 'running' AND "
            "user != (SELECT author FROM github_pull_requests "
            "         WHERE repository = :repo AND id = :prid)",
            {
                "repo": repo,
                "prid": pr_id,
            }
        )

        returnValue([reviewer for reviewer, in rows])


class Salon(object):
    emoji_rewrites = [
        # github started doing unicode characters for autocompleted emoji
        (u"\U0001F41F", ":fish:"),
        (u"\U0001F485", ":nail_care:"),
        (u"\U0001F487", ":haircut:"),
        (u"\U0001F453", ":eyeglasses:"),
        (u"\U0001F3C3", ":running:"),

        # github stopped autocompleting :running:
        (":runner:", ":running:"),

        # and now ":haircut:" is gone from github
        (":haircut_man:", ":haircut:"),
        (":haircut_woman:", ":haircut:"),

        # this is just for fun
        (":tropical_fish:", ":fish:"),
        (u"\U0001F420", ":fish:"),
        (":trumpet::skull:", ":fish:"),
        (":trumpet: :skull:", ":fish:"),
        (u"\U0001F3BA \U0001F480", ":fish:"),
        (u"\U0001F3BA\U0001F480", ":fish:"),
    ]

    messages_by_emoji = {
        ":fish:": "%(owner)s, %(user)s just :fish:'d your pull request "
                  "%(repo)s#%(id)s (%(short_url)s)",
        ":nail_care:": "%(owner)s, %(user)s has finished this review pass on "
                       "pull request %(repo)s#%(id)s (%(short_url)s)",
        ":haircut:": "%(reviewers)s: %(owner_de)s is ready for further review of "
                     "pull request %(repo)s#%(id)s (%(short_url)s)",
        ":eyeglasses:": "%(reviewers)s: %(user)s has requested your review "
                        "of %(repo)s#%(id)s (%(short_url)s)",
        ":running:": "%(owner)s, %(user)s is unable to review %(repo)s#%(id)s "
                     "(%(short_url)s) at this time. Please summon a new "
                     "reviewer.",
    }

    def __init__(self, config, bot, shortener, database):
        self.config = config
        self.bot = bot
        self.shortener = shortener
        self.database = SalonDatabase(database)

    @inlineCallbacks
    def dispatch_pullrequest(self, parsed):
        pull_request = parsed["pull_request"]
        timestamp = _parse_timestamp(pull_request["created_at"])
        repository_name = parsed["repository"]["full_name"]
        repository = self.config.repositories_by_name[repository_name]
        pull_request_id = parsed["number"]
        sender = self.config.nick_by_user(parsed["sender"]["login"])

        yield self.database.process_pullrequest(pull_request, repository_name)

        html_link = pull_request["_links"]["html"]["href"]
        short_url = yield self.shortener.make_short_url(html_link)

        if parsed["action"] == "review_requested":
            username = parsed["requested_reviewer"]["login"]
            yield self.database.add_review_request(
                repo=repository_name,
                pull_request_id=pull_request_id,
                username=username,
                timestamp=timestamp,
            )

            message = self.messages_by_emoji[":eyeglasses:"]
            self.bot.send_message(repository.channel, message % {
                "reviewers": self.config.nick_by_user(username),
                "user": dehilight(sender),
                "repo": repository_name,
                "id": pull_request_id,
                "short_url": short_url,
            })
        elif parsed["action"] == "review_request_removed":
            username = parsed["requested_reviewer"]["login"]
            yield self.database.remove_review_request(
                repo=repository_name,
                pull_request_id=pull_request_id,
                username=username,
            )
        elif parsed["action"] == "opened":
            message = ("%(user)s opened pull request #%(id)d (%(short_url)s) "
                       "on %(repo)s: %(title)s")
            self.bot.send_message(repository.channel, message % dict(
                user=dehilight(sender),
                id=pull_request_id,
                short_url=short_url,
                repo=repository_name,
                title=pull_request["title"][:72],
            ))

            reviewers = _extract_reviewers(pull_request["body"])
            reviewers = map(self.config.nick_by_user, reviewers)
            if reviewers:
                self.bot.send_message(repository.channel,
                                      "%(reviewers)s: %(user)s has requested "
                                      "your review of ^" % {
                                          "reviewers": ", ".join(reviewers),
                                          "user": dehilight(sender),
                                      })

    @classmethod
    def rewrite_emoji(cls, text):
        if not isinstance(text, unicode):
            text = text.decode("utf8")

        # github started using real unicode emoji when autocompleting
        for pattern, replacement in cls.emoji_rewrites:
            text = text.replace(pattern, replacement)

        return text

    def find_emoji(self, text):
        text = self.rewrite_emoji(text)

        for line in text.splitlines():
            if line.startswith(">"):
                continue
            for emoji, message in self.messages_by_emoji.iteritems():
                if emoji in line:
                    return emoji, message
        return None, None

    @inlineCallbacks
    def dispatch_comment(self, parsed):
        if parsed["action"] != "created":
            return

        body = parsed["comment"]["body"]
        emoji, message = self.find_emoji(body)
        if not emoji:
            return

        repository_name = parsed["repository"]["full_name"]
        repository = self.config.repositories_by_name[repository_name]
        html_link = parsed["issue"]["pull_request"]["html_url"]
        short_url = yield self.shortener.make_short_url(html_link)
        pr_id = int(parsed["issue"]["number"])
        timestamp = _parse_timestamp(parsed["comment"]["created_at"])

        yield self.database.update_review_state(
            repository_name, pr_id, parsed["comment"]["body"],
            timestamp, parsed["sender"]["login"], emoji)

        owner = self.config.nick_by_user(parsed["issue"]["user"]["login"])
        message_info = dict(
            user=dehilight(self.config.nick_by_user(parsed["sender"]["login"])),
            owner=owner,
            owner_de=dehilight(owner),
            id=str(pr_id),
            short_url=short_url,
            repo=repository_name,
        )

        if "%(reviewers)s" in message:
            if emoji == ":eyeglasses:":
                reviewers = _extract_reviewers(body)
                if not reviewers:
                    return
            else:
                reviewers = yield self.database.get_reviewers(repository_name,
                                                              pr_id)

            mapped_reviewers = map(self.config.nick_by_user, reviewers)
            message_info["reviewers"] = ", ".join(mapped_reviewers or
                                                  ["(no one in particular)"])

        self.bot.send_message(repository.channel, message % message_info)

    @inlineCallbacks
    def dispatch_review(self, parsed):
        if parsed["action"] != "submitted":
            return

        repository_name = parsed["repository"]["full_name"]
        repository = self.config.repositories_by_name[repository_name]
        html_link = parsed["pull_request"]["html_url"]
        short_url = yield self.shortener.make_short_url(html_link)
        pr_id = int(parsed["pull_request"]["number"])
        timestamp = _parse_timestamp(parsed["review"]["submitted_at"])

        emoji_by_state = {
            "approved": ":fish:",
            "changes_requested": ":nail_care:",
        }
        emoji = emoji_by_state.get(parsed["review"]["state"])
        if not emoji:
            return
        message = self.messages_by_emoji[emoji]

        yield self.database.update_review_state(
            repository_name, pr_id, parsed["review"]["body"],
            timestamp, parsed["sender"]["login"], emoji)

        owner = self.config.nick_by_user(parsed["pull_request"]["user"]["login"])
        message_info = dict(
            user=dehilight(self.config.nick_by_user(parsed["sender"]["login"])),
            owner=owner,
            owner_de=dehilight(owner),
            id=str(pr_id),
            short_url=short_url,
            repo=repository_name,
        )

        if "%(reviewers)s" in message:
            reviewers = yield self.database.get_reviewers(repository_name, pr_id)
            mapped_reviewers = map(self.config.nick_by_user, reviewers)
            message_info["reviewers"] = ", ".join(mapped_reviewers or
                                                  ["(no one in particular)"])

        self.bot.send_message(repository.channel, message % message_info)


class GitHubListener(ProtectedResource):
    isLeaf = True

    def __init__(self, config, http, bot, database):
        ProtectedResource.__init__(self, http)
        shortener = UrlShortener()

        push_dispatcher = PushDispatcher(config, bot, shortener)
        salon = Salon(config, bot, shortener, database)

        self.dispatchers = {
            "ping": push_dispatcher.dispatch_ping,
            "push": push_dispatcher.dispatch_push,
            "pull_request": salon.dispatch_pullrequest,
            "issue_comment": salon.dispatch_comment,
            "pull_request_review": salon.dispatch_review,
        }

    def _handle_request(self, request):
        event = request.requestHeaders.getRawHeaders("X-Github-Event")[-1]
        dispatcher = self.dispatchers.get(event)

        if dispatcher:
            post_data = request.args['payload'][0]
            parsed = json.loads(post_data)
            dispatcher(parsed)


def make_plugin(config, http, irc, database=None):
    gh_config = GitHubConfig(config)
    for channel in gh_config.channels:
        irc.channels.add(channel)

    http.root.putChild('github', GitHubListener(gh_config, http, irc.bot,
                                                database))
