from twisted.application import service

from dispatcher import Dispatcher
from conf import HaroldConfiguration
import irc
import http

# read configuration
config = HaroldConfiguration("harold.ini")
dispatcher = Dispatcher()

# build the application
application = service.Application("Harold")

# set up the irc service
irc_service = irc.make_service(config, dispatcher)
irc_service.setServiceParent(application)

# set up the http service
http_service = http.make_service(config, dispatcher)
http_service.setServiceParent(application)
