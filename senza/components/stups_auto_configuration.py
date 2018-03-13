import senza.stups.taupage as taupage

from senza.components.subnet_auto_configuration import component_subnet_auto_configuration
from senza.utils import ensure_keys


def component_stups_auto_configuration(definition, configuration, args, info, force, account_info):
    for channel in taupage.CHANNELS.values():
        most_recent_image = taupage.find_image(args.region, channel)
        if most_recent_image:
            configuration = ensure_keys(configuration, "Images", channel.image_mapping, args.region)
            configuration["Images"][channel.image_mapping][args.region] = most_recent_image.id
        elif channel == taupage.DEFAULT_CHANNEL:
            # Require at least one image from the stable channel
            raise Exception('No Taupage AMI found')

    component_subnet_auto_configuration(definition, configuration, args, info, force, account_info)

    return definition
