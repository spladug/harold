import json

from http import ProtectedResource
from shorturl import UrlShortener
from conf import PluginConfig, Option, tup

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

class PostReceiveDispatcher(object):
    def __init__(self, config, bot):
        self.config = config
        self.bot = bot
        self.shortener = UrlShortener()

    def _dispatch_commit(self, repository, branch, commit):
        author = commit['author']
        d = self.shortener.make_short_url(commit['url'])

        def onUrlShortened(short_url):
            self.bot.send_message(repository.channel,
                                  repository.format % {
                'repository': repository.name,
                'branch': branch,

                'commit_id': commit['id'][:7],
                'url': short_url,
                'author': author.get('username', author['name']),
                'summary': commit['message'].splitlines()[0]
            })
        d.addCallback(onUrlShortened)

    def dispatch(self, payload):
        parsed = json.loads(payload)
        repository_name = (parsed['repository']['owner']['name'] + '/' +
                           parsed['repository']['name'])
        repository = self.config.repositories_by_name[repository_name]
        branch = parsed['ref'].split('/')[-1]

        if not repository.branches or branch in repository.branches:
            for commit in parsed['commits']:
                self._dispatch_commit(repository, branch, commit)


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
