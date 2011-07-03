import json

from twisted.web import resource, server

class PostReceiveNotifier(resource.Resource):
    isLeaf = True

    def __init__(self, config, notifier):
        self.config = config
        self.notifier = notifier

    def render_POST(self, request):
        if request.postpath != ["harold", "post-receive", 
                                    self.config.http.secret]:
            return

        post_data = request.args['payload'][0]
        parsed = json.loads(post_data)
        repository_name = (parsed['repository']['owner']['name'] + '/' +
                           parsed['repository']['name'])
        repository = self.config.repositories_by_name[repository_name]

        for commit in parsed['commits']:
            self.notifier.addCommit(repository, commit)

        return ""

def make_site(config, commitqueue):
    root = PostReceiveNotifier(config, commitqueue)
    site = server.Site(root)
    site.displayTracebacks = False
    return site
