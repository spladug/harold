import importlib
import copy
import inspect


class PluginDependencyError(Exception):
    def __init__(self, plugin, unsatisfied):
        self.plugin = plugin
        self.unsatisfied = unsatisfied

    def __str__(self):
        return ("the %r plugin requires the %r plugin but it is "
                "not configured" % (self.plugin, self.unsatisfied))


class Plugin(object):
    def __init__(self):
        self.services = []

    def add_service(self, service):
        self.services.append(service)


def _import_plugin_modules(config):
    plugins = {"config": config}
    dependencies = {}
    optional_dependencies = {}

    config.PROVIDES_HAROLD_PLUGINS = ["config"]

    for plugin_name in config.plugin_names():
        plugin = importlib.import_module("harold.plugins." + plugin_name)
        plugins[plugin_name] = plugin

        try:
            plugin.PROVIDES_HAROLD_PLUGINS
        except AttributeError:
            plugin.PROVIDES_HAROLD_PLUGINS = [plugin_name]
        else:
            plugin.PROVIDES_HAROLD_PLUGINS.insert(0, plugin_name)

        args, varargs, kw, defaults = inspect.getargspec(plugin.make_plugin)

        if defaults:
            optional_count = len(defaults)
            dependencies[plugin_name] = set(args[:-optional_count])
            optional_dependencies[plugin_name] = set(args[-optional_count:])
        else:
            dependencies[plugin_name] = set(args)

    return plugins, dependencies, optional_dependencies


def _topological_sort(plugins, dependencies):
    dependencies = copy.deepcopy(dependencies)

    startup_order = []
    satisfied_plugins = ['config']  # config is a known-safe starting point
    while satisfied_plugins:
        satisfied = satisfied_plugins.pop()
        startup_order.append(satisfied)

        satisfied_plugin = plugins[satisfied]
        for plugin, deps in dependencies.items():
            for provided_interface in satisfied_plugin.PROVIDES_HAROLD_PLUGINS:
                if provided_interface in deps:
                    deps.remove(provided_interface)

            if len(deps) == 0:
                satisfied_plugins.append(plugin)
                del dependencies[plugin]

    assert len(dependencies) == 0

    return startup_order


def load_plugins(config):
    plugins, dependencies, optional_deps = _import_plugin_modules(config)

    # verify that we have the necessary plugins set up
    all_provided_interfaces = set()
    for p in plugins.itervalues():
        for i in p.PROVIDES_HAROLD_PLUGINS:
            all_provided_interfaces.add(i)

    for plugin_name, plugin_deps in dependencies.iteritems():
        for dep in plugin_deps:
            if dep not in all_provided_interfaces:
                raise PluginDependencyError(plugin_name, dep)

    # move optional dependencies to real dependencies for topo sort if we
    # determine that they do indeed exist.
    for plugin_name, plugin_optional_deps in optional_deps.iteritems():
        for optional_dep in plugin_optional_deps:
            if optional_dep in plugins:
                dependencies[plugin_name].add(optional_dep)
            else:
                print "%s: Discarding optional dependency %r" % (plugin_name,
                                                                 optional_dep)

    startup_order = _topological_sort(plugins, dependencies)

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
            for provided_interface in module.PROVIDES_HAROLD_PLUGINS:
                initialized_plugins[provided_interface] = p

    return (ip for name, ip in initialized_plugins.iteritems()
            if name != 'config')
