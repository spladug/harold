from twisted.web import resource, server

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

def make_site(config, dispatcher):
    harold = resource.Resource()
    harold.putChild('post-receive', _PostReceiveListener(config, dispatcher))
    harold.putChild('message', _MessageListener(config, dispatcher))

    root = resource.Resource()
    root.putChild('harold', harold)

    site = server.Site(root)
    site.displayTracebacks = False

    return site
