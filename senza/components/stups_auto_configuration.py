import boto3

from senza.components.configuration import component_configuration
from senza.utils import ensure_keys
from senza.aws import get_tag


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
    ec2 = boto3.resource('ec2', args.region)

    vpc_id = configuration.get('VpcId', account_info.VpcID)
    availability_zones = configuration.get('AvailabilityZones')

    server_subnets = []
    lb_subnets = []
    lb_internal_subnets = []
    for subnet in ec2.subnets.filter(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]):
        name = get_tag(subnet.tags, 'Name', '')
        if availability_zones and subnet.availability_zone not in availability_zones:
            # skip subnet as it's not in one of the given AZs
            continue
        if 'dmz' in name:
            lb_subnets.append(subnet.id)
        elif 'internal' in name:
            lb_internal_subnets.append(subnet.id)
            server_subnets.append(subnet.id)
        else:
            server_subnets.append(subnet.id)

    if not lb_subnets:
        # no DMZ subnets were found, just use the same set for both LB and instances
        lb_subnets = server_subnets

    configuration = ensure_keys(configuration, "ServerSubnets", args.region)
    configuration["ServerSubnets"][args.region] = server_subnets

    configuration = ensure_keys(configuration, "LoadBalancerSubnets", args.region)
    configuration["LoadBalancerSubnets"][args.region] = lb_subnets

    configuration = ensure_keys(configuration, "LoadBalancerInternalSubnets", args.region)
    configuration["LoadBalancerInternalSubnets"][args.region] = lb_internal_subnets

    most_recent_image = find_taupage_image(args.region)
    configuration = ensure_keys(configuration, "Images", 'LatestTaupageImage', args.region)
    configuration["Images"]['LatestTaupageImage'][args.region] = most_recent_image.id

    component_configuration(definition, configuration, args, info, force, account_info)

    return definition
