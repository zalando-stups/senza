import requests

from senza.components.subnet_auto_configuration import component_subnet_auto_configuration
from senza.utils import ensure_keys


def find_coreos_image(release_channel: str, region: str):
    '''Find the latest CoreOS AMI'''

    response = requests.get('https://coreos.com/dist/aws/aws-{}.json'.format(release_channel), timeout=5)
    response.raise_for_status()
    data = response.json()
    return data[region]['hvm']


def component_coreos_auto_configuration(definition, configuration, args, info, force, account_info):
    ami_id = find_coreos_image(configuration.get('ReleaseChannel') or 'stable', args.region)
    configuration = ensure_keys(configuration, "Images", 'LatestCoreOSImage', args.region)
    configuration["Images"]['LatestCoreOSImage'][args.region] = ami_id

    component_subnet_auto_configuration(definition, configuration, args, info, force, account_info)

    return definition
