import boto.ec2
import boto.vpc

from senza.components.configuration import component_configuration
from senza.utils import ensure_keys


def find_taupage_image(region: str):
    '''Find the latest Taupage AMI, first try private images, fallback to public'''
    ec2_conn = boto.ec2.connect_to_region(region)
    filters = {'name': '*Taupage-AMI-*',
               'is_public': 'false',
               'state': 'available',
               'root_device_type': 'ebs'}
    images = ec2_conn.get_all_images(filters=filters)
    if not images:
        public_filters = {'name': '*Taupage-Public-AMI-*',
                          'is_public': 'true',
                          'state': 'available',
                          'root_device_type': 'ebs'}
        images = ec2_conn.get_all_images(filters=public_filters)
    if not images:
        raise Exception('No Taupage AMI found')
    most_recent_image = sorted(images, key=lambda i: i.name)[-1]
    return most_recent_image


def component_stups_auto_configuration(definition, configuration, args, info, force):
    vpc_conn = boto.vpc.connect_to_region(args.region)

    availability_zones = configuration.get('AvailabilityZones')

    server_subnets = []
    lb_subnets = []
    lb_internal_subnets = []
    for subnet in vpc_conn.get_all_subnets():
        name = subnet.tags.get('Name', '')
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

    component_configuration(definition, configuration, args, info, force)

    return definition
