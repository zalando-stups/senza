import senza.stups.taupage as taupage

from senza.components.subnet_auto_configuration import component_subnet_auto_configuration
from senza.utils import ensure_keys


def component_stups_auto_configuration(definition, configuration, args, info, force, account_info):
    configuration = ensure_keys(configuration, "Images", taupage.DEFAULT_CHANNEL.image_mapping, args.region)
    component_subnet_auto_configuration(definition, configuration, args, info, force, account_info)

    return definition
