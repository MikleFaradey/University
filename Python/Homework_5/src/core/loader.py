from importlib.metadata import entry_points
from .registry import Registry
from .events import EventBus
from .module import ModuleContext
from .cli import CommandRegistry

def load(config: dict):
    available = {ep.name: ep for ep in entry_points(group='bank.modules')}
    names = config.get('modules', [])
    if len(names) != len(set(names)):
        raise ValueError('Repeated module in config')
    missing = set(names) - set(available)
    if missing:
        raise ValueError('Missing installed plugins: ' + ', '.join(sorted(missing)))
    ctx = ModuleContext(Registry(), EventBus(), CommandRegistry(), config)
    loaded = {}
    for name in names:
        plugin = available[name].load()()
        if plugin.name != name:
            raise RuntimeError('Plugin entry point name mismatch')
        plugin.initialize(ctx)
        loaded[name] = plugin
    for plugin in loaded.values():
        plugin.register_commands(ctx.commands)
    return (ctx, loaded)
