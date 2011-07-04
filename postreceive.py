import json

from shorturl import UrlShortener 

class PostReceiveDispatcher(object):
    def __init__(self, config, dispatcher):
        self.config = config
        self.dispatcher = dispatcher
        self.shortener = UrlShortener()

    def dispatch(self, payload):
        parsed = json.loads(payload)
        repository_name = (parsed['repository']['owner']['name'] + '/' +
                           parsed['repository']['name'])
        repository = self.config.repositories_by_name[repository_name]
        branch = parsed['ref'].split('/')[-1]

        if not repository.branches or branch in repository.branches:
            for commit in parsed['commits']:
                author = commit['author']

                d = self.shortener.make_short_url(commit['url'])
                def onUrlShortened(short_url):
                    self.dispatcher.send_message(repository.channel, 
                                                 repository.format % {
                        'repository': repository.name,
                        'branch': branch,

                        'commit_id': commit['id'][:7],
                        'url': short_url,
                        'author': author.get('username', author['name']),
                        'summary': commit['message'].splitlines()[0]
                    })
                d.addCallback(onUrlShortened)
