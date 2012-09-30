import time
import croniter

from twisted.internet import reactor

from harold.conf import PluginConfig, Option

ALARM_PREFIX = 'harold:alarm:'


class AlarmsConfig(object):
    def __init__(self, config, channels):
        self.alarms = []

        for section in config.parser.sections():
            if not section.startswith(ALARM_PREFIX):
                continue

            alarm = AlarmConfig(config, section=section)
            self.alarms.append(alarm)
            channels.add(alarm.channel)


class AlarmConfig(PluginConfig):
    channel = Option(str)
    message = Option(str)
    cronspec = Option(str)


class AlarmClock(object):
    def __init__(self, config, bot):
        self.bot = bot
        for alarm in config.alarms:
            alarm.croniter = croniter.croniter(alarm.cronspec)
            self._schedule_next_occurence(alarm)

    def _schedule_next_occurence(self, alarm):
        now = time.time()
        next_time = alarm.croniter.get_next()

        reactor.callLater(
            next_time - now,
            self._on_alarm_fired,
            alarm
        )

    def _on_alarm_fired(self, alarm):
        self.bot.send_message(
            alarm.channel,
            alarm.message
        )

        self._schedule_next_occurence(alarm)


def make_plugin(config, http, irc):
    alarms_config = AlarmsConfig(config, irc.channels)

    # if any alarms are set, the alarm clock will
    # register call-laters with the reactor which
    # will keep it alive
    AlarmClock(alarms_config, irc.bot)
