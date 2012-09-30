import importlib
import copy
import inspect


class Plugin(object):
    def __init__(self):
        self.services = []

    def add_service(self, service):
        self.services.append(service)


def _import_plugin_modules(config):
    plugins = {}
    dependencies = {}
    for plugin_name in config.plugin_names():
        plugin = importlib.import_module("harold.plugins." + plugin_name)
        plugins[plugin_name] = plugin

        args, varargs, kw, defaults = inspect.getargspec(plugin.make_plugin)
        dependencies[plugin_name] = set(args)

    return plugins, dependencies


def _topological_sort(dependencies):
    dependencies = copy.deepcopy(dependencies)

    startup_order = []
    satisfied_plugins = ['config']  # config is a known-safe starting point
    while satisfied_plugins:
        satisfied = satisfied_plugins.pop()
        startup_order.append(satisfied)

        for plugin, deps in dependencies.items():
            if satisfied in deps:
                deps.remove(satisfied)

            if len(deps) == 0:
                satisfied_plugins.append(plugin)
                del dependencies[plugin]

    assert len(dependencies) == 0

    return startup_order


def load_plugins(config):
    plugins, dependencies = _import_plugin_modules(config)
    startup_order = _topological_sort(dependencies)

    initialized_plugins = {'config': config}
    for plugin in startup_order:
        if plugin == 'config':
            continue

        module = plugins[plugin]
        args = dict((name, initialized)
                    for name, initialized in initialized_plugins.iteritems()
                    if name in dependencies[plugin])
        p = module.make_plugin(**args)
        if p:
            initialized_plugins[plugin] = p

    return (ip for name, ip in initialized_plugins.iteritems()
            if name != 'config')
