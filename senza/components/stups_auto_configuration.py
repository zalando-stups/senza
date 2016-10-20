import boto3

from senza.components.subnet_auto_configuration import component_subnet_auto_configuration
from senza.utils import ensure_keys


def find_taupage_image(region: str):
    '''Find the latest Taupage AMI, first try private images, fallback to public'''
    ec2 = boto3.resource('ec2', region)
    filters = [{'Name': 'name', 'Values': ['*Taupage-AMI-*']},
               {'Name': 'is-public', 'Values': ['false']},
               {'Name': 'state', 'Values': ['available']},
               {'Name': 'root-device-type', 'Values': ['ebs']}]
    images = list(ec2.images.filter(Filters=filters))
    if not images:
        public_filters = [{'Name': 'name', 'Values': ['*Taupage-Public-AMI-*']},
                          {'Name': 'is-public', 'Values': ['true']},
                          {'Name': 'state', 'Values': ['available']},
                          {'Name': 'root-device-type', 'Values': ['ebs']}]
        images = list(ec2.images.filter(Filters=public_filters))
    if not images:
        raise Exception('No Taupage AMI found')
    most_recent_image = sorted(images, key=lambda i: i.name)[-1]
    return most_recent_image


def component_stups_auto_configuration(definition, configuration, args, info, force, account_info):
    most_recent_image = find_taupage_image(args.region)
    configuration = ensure_keys(configuration, "Images", 'LatestTaupageImage', args.region)
    configuration["Images"]['LatestTaupageImage'][args.region] = most_recent_image.id

    component_subnet_auto_configuration(definition, configuration, args, info, force, account_info)

    return definition
