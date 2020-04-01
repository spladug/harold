def make_application(ini_file):
    import itertools

    from twisted.application.service import Application

    from harold.conf import HaroldConfiguration
    from harold.plugins import database
    from harold.plugins import deploy
    from harold.plugins import github
    from harold.plugins import http
    from harold.plugins import httpchat
    from harold.plugins import salons
    from harold.plugins import slack

    application = Application("Harold")

    config = HaroldConfiguration(ini_file)
    http_plugin = http.make_plugin(config)
    db_plugin = database.make_plugin(config)
    slack_plugin = slack.make_plugin(config, http_plugin)
    salons_plugin = salons.make_plugin(db_plugin)

    github.make_plugin(http_plugin, slack_plugin, salons_plugin, db_plugin)
    deploy.make_plugin(config, http_plugin, slack_plugin, salons_plugin)
    httpchat.make_plugin(http_plugin, slack_plugin)

    services = itertools.chain(
        http_plugin.services,
        db_plugin.services,
        slack_plugin.services,
        salons_plugin.services,
    )
    for service in services:
        service.setServiceParent(application)

    return application
