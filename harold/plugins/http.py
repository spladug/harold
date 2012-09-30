from twisted.web import resource, server
from twisted.application import internet

from harold.plugin import Plugin
from harold.conf import PluginConfig, Option

class HttpConfig(PluginConfig):
    port = Option(int, default=80)
    secret = Option(str)

class ProtectedResource(resource.Resource):
    def __init__(self, http):
        self.http = http

    def render_POST(self, request):
        if request.postpath != [self.http.secret]:
            return ""

        self._handle_request(request)

        return ""


def make_plugin(config):
    http_config = HttpConfig(config)

    root = resource.Resource()
    harold = resource.Resource()
    root.putChild('harold', harold)
    site = server.Site(root)
    site.displayTracebacks = False

    plugin = Plugin()
    plugin.root = harold
    plugin.secret = http_config.secret
    plugin.add_service(internet.TCPServer(http_config.port, site))
    return plugin
