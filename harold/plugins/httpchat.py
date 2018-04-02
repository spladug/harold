from harold.plugins.http import ProtectedResource


class MessageListener(ProtectedResource):
    isLeaf = True

    def __init__(self, http, dispatcher):
        ProtectedResource.__init__(self, http)
        self.dispatcher = dispatcher

    def _handle_request(self, request):
        channel = request.args['channel'][0]
        try:
            message = unicode(request.args['message'][0], 'utf-8')
        except UnicodeDecodeError:
            return
        else:
            self.dispatcher.send_message(channel, message)


def make_plugin(http, irc):
    http.root.putChild('message', MessageListener(http, irc.bot))
