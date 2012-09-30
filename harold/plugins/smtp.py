import cStringIO

from twisted.internet import reactor, ssl
from twisted.internet.defer import Deferred
from twisted.mail import smtp

from harold.plugin import Plugin
from harold.conf import PluginConfig, Option


class SmtpConfig(PluginConfig):
    host = Option(str)
    port = Option(int)
    use_ssl = Option(bool, default=True)
    username = Option(str)
    password = Option(str)


class SmtpSender(object):
    def __init__(self, config):
        self.config = config
        self.context = ssl.ClientContextFactory()

    def _on_error(self, result):
        print "failed to send email: %r" % result

    def __call__(self, sender, recipients, msg):
        print "Hello!"
        deferred = Deferred()

        msg['From'] = sender
        msg['To'] = ', '.join(recipients)

        factory = smtp.ESMTPSenderFactory(
            self.config.username,
            self.config.password,
            sender,
            recipients,
            cStringIO.StringIO(msg.as_string()),
            deferred,
            contextFactory=self.context,
            requireTransportSecurity=False,
            retries=0,
        )

        deferred.addErrback(self._on_error)

        if self.config.use_ssl:
            reactor.connectSSL(
                self.config.host,
                self.config.port,
                factory,
                self.context
            )
        else:
            reactor.connectTCP(
                self.config.host,
                self.config.port,
                factory
            )


def make_plugin(config):
    smtp_config = SmtpConfig(config)

    p = Plugin()
    p.username = smtp_config.username
    p.sendmail = SmtpSender(smtp_config)
    return p
