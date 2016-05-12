from types import ModuleType, FunctionType
import pkg_resources


def get_template_description(name, module: ModuleType):
    return '{}: {}'.format(name, (module.__doc__ or "").strip())


def has_functions(module, names):
    return all(isinstance(getattr(module, function_name, None), FunctionType) for function_name in names)


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
            # make sure the entry point resolves to a module with the essential interface functions
            if (isinstance(module, ModuleType) and
               has_functions(module, ('gather_user_variables', 'generate_definition'))):
                template_modules[e.name] = module
    return template_modules
