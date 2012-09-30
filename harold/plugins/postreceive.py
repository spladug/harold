import json

from harold.plugins.http import ProtectedResource
from harold.shorturl import UrlShortener
from harold.conf import PluginConfig, Option, tup

REPOSITORY_PREFIX = 'harold:repository:'

class PostReceiveConfig(object):
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


class PostReceiveDispatcher(object):
    def __init__(self, config, bot):
        self.config = config
        self.bot = bot
        self.shortener = UrlShortener()

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
        url = "http://github.com/%s/compare/%s...%s" % (repository.name,
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

    def dispatch(self, payload):
        parsed = json.loads(payload)
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


class PostReceiveListener(ProtectedResource):
    isLeaf = True

    def __init__(self, config, http, bot):
        ProtectedResource.__init__(self, http)
        self.dispatcher = PostReceiveDispatcher(config, bot)

    def _handle_request(self, request):
        post_data = request.args['payload'][0]
        self.dispatcher.dispatch(post_data)


def make_plugin(config, http, irc):
    pr_config = PostReceiveConfig(config, irc.channels)

    http.root.putChild('post-receive',
                       PostReceiveListener(pr_config, http, irc.bot))
