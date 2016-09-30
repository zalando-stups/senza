"""
Random functions that are useful in several places and not don't fall under
the domain of any other module.
"""

import re
import pystache


def named_value(dictionary):
    """
    Gets the name and value of a dict with a single key (for example SenzaInfo
    parameters or Senza Components)
    """
    return next(iter(dictionary.items()))


def ensure_keys(dict_obj, *keys):
    """
    Ensure ``dict_obj`` has the hierarchy ``{keys[0]: {keys[1]: {...}}}``

    The inner most key will have ``{}`` has value if didn't exist already.
    """
    if len(keys) == 0:
        return dict_obj
    else:
        first, rest = keys[0], keys[1:]
        if first not in dict_obj:
            dict_obj[first] = {}
        dict_obj[first] = ensure_keys(dict_obj[first], *rest)
        return dict_obj


def camel_case_to_underscore(name):
    """
    Converts name from CamelCase to snake_case
    """
    return re.sub('([a-z0-9])([A-Z])', r'\1_\2', name).lower()


def pystache_render(*args, **kwargs):
    """
    Render pystache template with strict mode
    """
    render = pystache.Renderer(missing_tags='strict')
    return render.render(*args, **kwargs)
