from ConfigParser import RawConfigParser

from twisted.application.service import Application


def make_application(ini_file):
    from harold.plugins import database
    from harold.plugins import deploy
    from harold.plugins import github
    from harold.plugins import http
    from harold.plugins import httpchat
    from harold.plugins import salons
    from harold.plugins import slack

    application = Application("Harold")

    parser = RawConfigParser()
    with open(ini_file) as fp:
        parser.readfp(fp)

    # TODO: ditch the separate config sections next
    def plugin_config(name):
        return dict(parser.items("harold:plugin:" + name))

    http_plugin = http.make_plugin(application, plugin_config("http"))
    slack_plugin = slack.make_plugin(application, plugin_config("slack"))
    db_plugin = database.make_plugin(plugin_config("database"))
    salons_plugin = salons.make_plugin(db_plugin)

    github.make_plugin(http_plugin, slack_plugin, salons_plugin, db_plugin)
    deploy.make_plugin(plugin_config("deploy"), http_plugin, slack_plugin, salons_plugin)
    httpchat.make_plugin(http_plugin, slack_plugin)

    return application
