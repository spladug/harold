from ConfigParser import RawConfigParser, NoOptionError

plugin_prefix = "harold:plugin:"

NoDefault = object()


class HaroldConfiguration(object):
    def __init__(self, filenames):
        self.parser = RawConfigParser()
        self.parser.read(filenames)

    def plugin_names(self):
        for section in self.parser.sections():
            if not section.startswith(plugin_prefix):
                continue

            yield section[len(plugin_prefix):]


class Option(object):
    def __init__(self, convert, default=NoDefault):
        self.convert = convert
        self.default = default


def tup(option):
    return [x.strip() for x in option.split(',') if x]


class PluginConfig(object):
    def __init__(self, config, section=None):
        if not section:
            plugin_name = self.__module__[len("harold.plugins."):]
            section = plugin_prefix + plugin_name

        for name, contents in vars(type(self)).iteritems():
            if not isinstance(contents, Option):
                continue

            try:
                value = config.parser.get(section, name)
                value = contents.convert(value)
            except NoOptionError:
                if contents.default is NoDefault:
                    raise
                value = contents.default

            setattr(self, name, value)
