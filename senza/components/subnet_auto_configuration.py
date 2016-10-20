import boto3

from senza.components.configuration import component_configuration
from senza.utils import ensure_keys
from senza.aws import get_tag


def component_subnet_auto_configuration(definition, configuration, args, info, force, account_info):
    ec2 = boto3.resource('ec2', args.region)

    vpc_id = configuration.get('VpcId', account_info.VpcID)
    availability_zones = configuration.get('AvailabilityZones')
    public_only = configuration.get('PublicOnly')

    server_subnets = []
    lb_subnets = []
    lb_internal_subnets = []
    all_subnets = []
    for subnet in ec2.subnets.filter(Filters=[{'Name': 'vpc-id', 'Values': [vpc_id]}]):
        name = get_tag(subnet.tags, 'Name', '')
        if availability_zones and subnet.availability_zone not in availability_zones:
            # skip subnet as it's not in one of the given AZs
            continue
        all_subnets.append(subnet.id)
        if public_only:
            if 'dmz' in name:
                lb_subnets.append(subnet.id)
                lb_internal_subnets.append(subnet.id)
                server_subnets.append(subnet.id)
        else:
            if 'dmz' in name:
                lb_subnets.append(subnet.id)
            elif 'internal' in name:
                lb_internal_subnets.append(subnet.id)
                server_subnets.append(subnet.id)
            else:
                server_subnets.append(subnet.id)

    if not lb_subnets:
        if public_only:
            # assume default AWS VPC setup with all subnets being public
            lb_subnets = all_subnets
            lb_internal_subnets = all_subnets
            server_subnets = all_subnets
        else:
            # no DMZ subnets were found, just use the same set for both LB and instances
            lb_subnets = server_subnets

    configuration = ensure_keys(configuration, "ServerSubnets", args.region)
    configuration["ServerSubnets"][args.region] = server_subnets

    configuration = ensure_keys(configuration, "LoadBalancerSubnets", args.region)
    configuration["LoadBalancerSubnets"][args.region] = lb_subnets

    configuration = ensure_keys(configuration, "LoadBalancerInternalSubnets", args.region)
    configuration["LoadBalancerInternalSubnets"][args.region] = lb_internal_subnets

    component_configuration(definition, configuration, args, info, force, account_info)

    return definition
