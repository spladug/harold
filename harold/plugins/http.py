from twisted.web import resource, server
from twisted.application import internet
from twisted.internet import reactor
from twisted.internet.endpoints import serverFromString

from harold.plugin import Plugin
from harold.conf import PluginConfig, Option


def constant_time_compare(actual, expected):
    """
    Returns True if the two strings are equal, False otherwise

    The time taken is dependent on the number of characters provided
    instead of the number of characters that match.
    """
    actual_len = len(actual)
    expected_len = len(expected)
    result = actual_len ^ expected_len
    if expected_len > 0:
        for i in xrange(actual_len):
            result |= ord(actual[i]) ^ ord(expected[i % expected_len])
    return result == 0


class HttpConfig(PluginConfig):
    endpoint = Option(str)
    secret = Option(str)
    public_root = Option(str, default="")


class ProtectedResource(resource.Resource):
    def __init__(self, http):
        self.http = http

    def render_POST(self, request):
        if request.postpath:
            secret = request.postpath.pop(-1)
            if constant_time_compare(secret, self.http.secret):
                self._handle_request(request)

        return ""


def make_plugin(config):
    http_config = HttpConfig(config)

    root = resource.Resource()
    harold = resource.Resource()
    root.putChild('harold', harold)
    site = server.Site(root)
    site.displayTracebacks = False

    endpoint = serverFromString(reactor, http_config.endpoint)
    service = internet.StreamServerEndpointService(endpoint, site)

    plugin = Plugin()
    plugin.root = harold
    plugin.secret = http_config.secret
    plugin.add_service(service)

    return plugin
