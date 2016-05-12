from types import ModuleType
import pkg_resources


def get_template_description(name, module: ModuleType):
    return '{}: {}'.format(name, (module.__doc__ or "").strip())


def get_templates() -> dict:
    """
    Returns a dict with all the template modules
    """
    entry_points = pkg_resources.iter_entry_points('senza.templates')
    template_modules = {}
    for e in entry_points:  # type: pkg_resources.EntryPoint
        try:
            module = e.resolve()
        except ImportError:
            # ignore bad entry points
            continue
        else:
            if isinstance(module, ModuleType):  # avoid objects that are not modules
                template_modules[e.name] = module
    return template_modules
