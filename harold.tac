from twisted.application import service

from conf import HaroldConfiguration
import irc
import http
import jabber
import ident

# read configuration
config = HaroldConfiguration("harold.ini")

# build the application
application = service.Application("Harold")

# make the http root resource
http_root, harold_root = http.make_root(config)

# a really stupid ident service
if hasattr(config, 'ident'):
    ident_service = ident.make_service(config, harold_root)
    ident_service.setServiceParent(application)

# set up the irc service
if hasattr(config, 'irc'):
    irc_service = irc.make_service(config, harold_root)
    irc_service.setServiceParent(application)

# set up jabber
if hasattr(config, 'jabber'):
    jabber_service = jabber.make_service(config, harold_root)
    jabber_service.setServiceParent(application)

# set up the http service
http_service = http.make_service(config, http_root)
http_service.setServiceParent(application)
