import json

from harold.plugins.http import ProtectedResource
from harold.shorturl import UrlShortener
from harold.conf import PluginConfig, Option, tup

REPOSITORY_PREFIX = 'harold:repository:'


class GitHubConfig(object):
    def __init__(self, config, channels):
        self.repositories_by_name = {}

        for section in config.parser.sections():
            if not section.startswith(REPOSITORY_PREFIX):
                continue

            repository = RepositoryConfig(config, section=section)
            repository.name = section[len(REPOSITORY_PREFIX):]
            self.repositories_by_name[repository.name] = repository
            channels.add(repository.channel)


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
                'author': _get_commit_author(commit),
                'summary': commit['message'].splitlines()[0]
            })
        d.addCallback(onUrlShortened)

    def _dispatch_bundle(self, info, repository, branch, commits):
        authors = set()
        for commit in commits:
            authors.add(_get_commit_author(commit))
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
                'authors': ', '.join(authors),
                'commit_count': len(commits),
                'commit_range': commit_range,
                'url': short_url,
            })
        d.addCallback(onUrlShortened)

    def dispatch(self, parsed):
        repository_name = (parsed['repository']['owner']['name'] + '/' +
                           parsed['repository']['name'])
        repository = self.config.repositories_by_name[repository_name]
        branch = parsed['ref'].split('/')[-1]
        commits = parsed['commits']

        if not repository.branches or branch in repository.branches:
            if len(commits) <= repository.max_commit_count:
                for commit in commits:
                    self._dispatch_commit(repository, branch, commit)
            else:
                self._dispatch_bundle(parsed, repository, branch, commits)


class Salon(object):
    messages_by_emoji = {
        ":fish:": "%(owner)s, %(user)s just ><))>'d your pull request "
                  "%(repo)s#%(id)s (%(short_url)s)",
        ":nail_care:": "%(owner)s, %(user)s is awaiting your response to "
                       "review of pull request %(repo)s#%(id)s "
                       "(%(short_url)s)",
        ":haircut:": "%(owner)s is ready for further review of pull request "
                     "%(repo)s#%(id)s (%(short_url)s)",
    }

    def __init__(self, config, bot, shortener):
        self.config = config
        self.bot = bot
        self.shortener = shortener

    def dispatch_pullrequest(self, parsed):
        action = parsed["action"]
        if action != "opened":
            return

        repository_name = parsed["repository"]["full_name"]
        repository = self.config.repositories_by_name[repository_name]

        html_link = parsed["pull_request"]["_links"]["html"]["href"]
        d = self.shortener.make_short_url(html_link)
        def onUrlShortened(short_url):
            message = ("%(user)s opened pull request #%(id)d (%(short_url)s) "
                       "on %(repo)s: %(title)s")
            self.bot.send_message(repository.channel, message % dict(
                user=parsed["sender"]["login"],
                id=parsed["number"],
                short_url=short_url,
                repo=repository_name,
                title=parsed["pull_request"]["title"][:72],
            ))
        d.addCallback(onUrlShortened)

    def dispatch_comment(self, parsed):
        action = parsed["action"]
        if action != "created":
            return

        body = parsed["comment"]["body"]
        for emoji, message in self.messages_by_emoji.iteritems():
            if emoji in body:
                self._announce_emoji(message, parsed)
                break

    def _announce_emoji(self, message, parsed):
        repository_name = parsed["repository"]["full_name"]
        repository = self.config.repositories_by_name[repository_name]
        html_link = parsed["issue"]["pull_request"]["html_url"]
        d = self.shortener.make_short_url(html_link)
        def onUrlShortened(short_url):
            self.bot.send_message(repository.channel, message % dict(
                user=parsed["sender"]["login"],
                owner=parsed["issue"]["user"]["login"],
                id=parsed["issue"]["number"],
                short_url=short_url,
                repo=repository_name,
            ))
        d.addCallback(onUrlShortened)


class GitHubListener(ProtectedResource):
    isLeaf = True

    def __init__(self, config, http, bot):
        ProtectedResource.__init__(self, http)
        shortener = UrlShortener()

        push_dispatcher = PushDispatcher(config, bot, shortener)
        salon = Salon(config, bot, shortener)

        self.dispatchers = {
            "push": push_dispatcher.dispatch,
            "pull_request": salon.dispatch_pullrequest,
            "issue_comment": salon.dispatch_comment,
        }

    def _handle_request(self, request):
        event = request.requestHeaders.getRawHeaders("X-Github-Event")[-1]
        dispatcher = self.dispatchers.get(event)

        if dispatcher:
            post_data = request.args['payload'][0]
            parsed = json.loads(post_data)
            dispatcher(parsed)


def make_plugin(config, http, irc):
    gh_config = GitHubConfig(config, irc.channels)

    http.root.putChild('github', GitHubListener(gh_config, http, irc.bot))
