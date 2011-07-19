from twisted.web import resource, server
from twisted.application import internet


class ProtectedResource(resource.Resource):
    def __init__(self, config):
        self.config = config

    def render_POST(self, request):
        if request.postpath != [self.config.http.secret]:
            return ""

        self._handle_request(request)

        return ""


def make_root(config):
    harold = resource.Resource()
    root = resource.Resource()
    root.putChild('harold', harold)
    return root, harold


def make_service(config, root):
    site = server.Site(root)
    site.displayTracebacks = False

    return internet.TCPServer(config.http.port, site)
