def make_application(ini_file):
    from twisted.application import service
    from harold.conf import HaroldConfiguration
    from harold import plugin

    # read configuration
    config = HaroldConfiguration(ini_file)

    # load the service modules
    plugins = plugin.load_plugins(config)

    # build the application
    application = service.Application("Harold")
    for p in plugins:
        for svc in p.services:
            svc.setServiceParent(application)

    return application
