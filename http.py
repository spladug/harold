import json

from twisted.web import resource

class PostReceiveNotifier(resource.Resource):
    isLeaf = True

    def __init__(self, notifier):
        self.notifier = notifier

    def render_POST(self, request):
        data = request.args['payload'][0]
        parsed = json.loads(data)
        for commit in parsed['commits']:
            self.notifier.enqueue_notification(commit)
        return ""
