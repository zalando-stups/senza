

def named_value(d):
    return next(iter(d.items()))


def ensure_keys(dict, *keys):
    if len(keys) == 0:
        return dict
    else:
        first, rest = keys[0], keys[1:]
        if first not in dict:
            dict[first] = {}
        dict[first] = ensure_keys(dict[first], *rest)
        return dict
