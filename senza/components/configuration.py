
from senza.utils import ensure_keys, named_value


def format_params(args):
    items = [(key, val) for key, val in sorted(args.__dict__.items()) if key not in ('region', 'version')]
    return ', '.join(['{}: {}'.format(key, val) for key, val in items])


def get_default_description(info, args):
    return '{} ({})'.format(info['StackName'].title().replace('-', ' '), format_params(args))


def component_configuration(definition, configuration, args, info, force, account_info):
    # define parameters
    # http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/parameters-section-structure.html
    if "Parameters" in info and configuration.get('DefineParameters', True):
        definition = ensure_keys(definition, "Parameters")
        default_parameter = {
            "Type": "String"
        }
        for parameter in info["Parameters"]:
            name, value = named_value(parameter)
            value_default = default_parameter.copy()
            value_default.update(value)
            definition["Parameters"][name] = value_default

    if 'Description' not in definition:
        # set some sane default stack description
        # we need to truncate at 1024 chars (should be Bytes actually)
        # see http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/template-description-structure.html
        definition['Description'] = get_default_description(info, args)[:1024]

    # ServerSubnets
    for region, subnets in configuration.get('ServerSubnets', {}).items():
        definition = ensure_keys(definition, "Mappings", "ServerSubnets", region)
        definition["Mappings"]["ServerSubnets"][region]["Subnets"] = subnets

    # LoadBalancerSubnets
    for region, subnets in configuration.get('LoadBalancerSubnets', {}).items():
        definition = ensure_keys(definition, "Mappings", "LoadBalancerSubnets", region)
        definition["Mappings"]["LoadBalancerSubnets"][region]["Subnets"] = subnets

    # LoadBalancerInternalSubnets
    for region, subnets in configuration.get('LoadBalancerInternalSubnets', {}).items():
        definition = ensure_keys(definition, "Mappings", "LoadBalancerInternalSubnets", region)
        definition["Mappings"]["LoadBalancerInternalSubnets"][region]["Subnets"] = subnets

    # Images
    for name, image in configuration.get('Images', {}).items():
        for region, ami in image.items():
            definition = ensure_keys(definition, "Mappings", "Images", region, name)
            definition["Mappings"]["Images"][region][name] = ami

    return definition
