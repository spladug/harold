from twisted.web import resource, server
from twisted.application import internet

from postreceive import PostReceiveDispatcher


class _Listener(resource.Resource):
    def __init__(self, config):
        self.config = config

    def render_POST(self, request):
        if request.postpath != [self.config.http.secret]:
            return ""

        self._handle_request(request)

        return ""


class _PostReceiveListener(_Listener):
    isLeaf = True

    def __init__(self, config, dispatcher):
        _Listener.__init__(self, config)
        self.dispatcher = PostReceiveDispatcher(config, dispatcher)

    def _handle_request(self, request):
        post_data = request.args['payload'][0]
        self.dispatcher.dispatch(post_data)


class _MessageListener(_Listener):
    isLeaf = True

    def __init__(self, config, dispatcher):
        _Listener.__init__(self, config)
        self.dispatcher = dispatcher

    def _handle_request(self, request):
        channel = request.args['channel'][0]
        message = request.args['message'][0]
        self.dispatcher.send_message(channel, message)


class _SetTopicListener(_Listener):
    isLeaf = True

    def __init__(self, config, dispatcher):
        _Listener.__init__(self, config)
        self.dispatcher = dispatcher

    def _handle_request(self, request):
        channel = request.args['channel'][0]
        new_topic = request.args['topic'][0]
        self.dispatcher.set_topic(channel, new_topic)


class _RestoreTopicListener(_Listener):
    isLeaf = True

    def __init__(self, config, dispatcher):
        _Listener.__init__(self, config)
        self.dispatcher = dispatcher

    def _handle_request(self, request):
        channel = request.args['channel'][0]
        self.dispatcher.restore_topic(channel)


def make_service(config, dispatcher):
    harold = resource.Resource()
    harold.putChild('post-receive', _PostReceiveListener(config, dispatcher))
    harold.putChild('message', _MessageListener(config, dispatcher))

    topic_root = resource.Resource()
    harold.putChild('topic', topic_root)
    topic_root.putChild('set', _SetTopicListener(config, dispatcher))
    topic_root.putChild('restore', _RestoreTopicListener(config, dispatcher))

    root = resource.Resource()
    root.putChild('harold', harold)

    site = server.Site(root)
    site.displayTracebacks = False

    return internet.TCPServer(config.http.port, site)
