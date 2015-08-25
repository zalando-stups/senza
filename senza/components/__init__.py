import importlib

from senza.utils import camel_case_to_underscore, pystache_render


def get_component(componenttype: str):
    '''Get component function by type name (e.g. "Senza::MyComponent")'''

    prefix, _, componenttype = componenttype.partition('::')
    root_package = camel_case_to_underscore(prefix)
    module_name = camel_case_to_underscore(componenttype)
    try:
        module = importlib.import_module('{}.components.{}'.format(root_package, module_name))
    except ImportError:
        # component (module) not found
        return None
    function_name = 'component_{}'.format(module_name)
    return getattr(module, function_name)


def evaluate_template(template, info, components, args, account_info):
    data = {"SenzaInfo": info,
            "SenzaComponents": components,
            "Arguments": args,
            "AccountInfo": account_info}
    result = pystache_render(template, data)
    return result
