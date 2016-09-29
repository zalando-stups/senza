import click
from senza.aws import resolve_security_groups
from senza.components.elastic_load_balancer import ALLOWED_LOADBALANCER_SCHEMES, get_load_balancer_name, get_ssl_cert

from ..cli import AccountArguments, TemplateArguments
from ..manaus.route53 import convert_cname_records_to_alias

SENZA_PROPERTIES = frozenset(['Domains', 'HealthCheckPath', 'HealthCheckPort', 'HealthCheckProtocol',
                              'HTTPPort', 'Name', 'SecurityGroups', 'SSLCertificateId', 'Type'])
ALLOWED_HEALTH_CHECK_PROTOCOLS = frozenset(["HTTP", "HTTPS"])


def get_listeners(lb_name, target_group_name, subdomain, main_zone, configuration,
                  account_info: AccountArguments):
    ssl_cert = get_ssl_cert(subdomain, main_zone, configuration, account_info)
    return [{
        'Type': 'AWS::ElasticLoadBalancingV2::Listener',
        'Properties': {
            "Certificates": [{'CertificateArn': ssl_cert}],
            "Protocol": "HTTPS",
            "DefaultActions": [{'Type': 'forward', 'TargetGroupArn': {'Ref': target_group_name}}],
            'LoadBalancerArn': {'Ref': lb_name},
            "Port": 443
        }
    }]


def component_elastic_load_balancer_v2(definition,
                                       configuration: dict,
                                       args: TemplateArguments,
                                       info: dict,
                                       force,
                                       account_info: AccountArguments):
    lb_name = configuration["Name"]
    # domains pointing to the load balancer
    subdomain = ''
    main_zone = None
    for name, domain in configuration.get('Domains', {}).items():
        name = '{}{}'.format(lb_name, name)

        domain_name = "{0}.{1}".format(domain["Subdomain"], domain["Zone"])

        convert_cname_records_to_alias(domain_name)

        properties = {"Type": "A",
                      "Name": domain_name,
                      "HostedZoneName": domain["Zone"],
                      "AliasTarget": {"HostedZoneId": {"Fn::GetAtt": [lb_name,
                                                                      "CanonicalHostedZoneID"]},
                                      "DNSName": {"Fn::GetAtt": [lb_name, "DNSName"]}}}
        definition["Resources"][name] = {"Type": "AWS::Route53::RecordSet",
                                         "Properties": properties}

        if domain["Type"] == "weighted":
            definition["Resources"][name]["Properties"]['Weight'] = 0
            definition["Resources"][name]["Properties"]['SetIdentifier'] = "{0}-{1}".format(info["StackName"],
                                                                                            info["StackVersion"])
            subdomain = domain['Subdomain']
            main_zone = domain['Zone']  # type: str

    target_group_name = lb_name + 'TargetGroup'
    listeners = configuration.get('Listeners') or get_listeners(
        lb_name, target_group_name, subdomain, main_zone, configuration, account_info)

    health_check_protocol = configuration.get('HealthCheckProtocol') or 'HTTP'

    if health_check_protocol not in ALLOWED_HEALTH_CHECK_PROTOCOLS:
        raise click.UsageError('Protocol "{}" is not supported for LoadBalancer'.format(health_check_protocol))

    health_check_path = configuration.get("HealthCheckPath") or '/health'
    health_check_port = configuration.get("HealthCheckPort") or configuration["HTTPPort"]

    if configuration.get('NameSuffix'):
        version = '{}-{}'.format(info["StackVersion"],
                                 configuration['NameSuffix'])
        loadbalancer_name = get_load_balancer_name(info["StackName"], version)
        del(configuration['NameSuffix'])
    else:
        loadbalancer_name = get_load_balancer_name(info["StackName"],
                                                   info["StackVersion"])

    loadbalancer_scheme = configuration.get('Scheme') or 'internal'
    if loadbalancer_scheme == 'internet-facing':
        click.secho('You are deploying an internet-facing ELB that will be '
                    'publicly accessible! You should have OAUTH2 and HTTPS '
                    'in place!', bold=True, err=True)

    if loadbalancer_scheme not in ALLOWED_LOADBALANCER_SCHEMES:
        raise click.UsageError('Scheme "{}" is not supported for LoadBalancer'.format(loadbalancer_scheme))

    if loadbalancer_scheme == "internal":
        loadbalancer_subnet_map = "LoadBalancerInternalSubnets"
    else:
        loadbalancer_subnet_map = "LoadBalancerSubnets"

    tags = [
        # Tag "Name"
        {
            "Key": "Name",
            "Value": "{0}-{1}".format(info["StackName"], info["StackVersion"])
        },
        # Tag "StackName"
        {
            "Key": "StackName",
            "Value": info["StackName"],
        },
        # Tag "StackVersion"
        {
            "Key": "StackVersion",
            "Value": info["StackVersion"]
        }
    ]

    # load balancer
    definition["Resources"][lb_name] = {
        "Type": "AWS::ElasticLoadBalancingV2::LoadBalancer",
        "Properties": {
            'Name': loadbalancer_name,
            'Scheme': loadbalancer_scheme,
            'SecurityGroups': resolve_security_groups(configuration["SecurityGroups"], args.region),
            'Subnets': {"Fn::FindInMap": [loadbalancer_subnet_map, {"Ref": "AWS::Region"}, "Subnets"]},
            "Tags": tags
        }
    }
    definition["Resources"][target_group_name] = {
        'Type': 'AWS::ElasticLoadBalancingV2::TargetGroup',
        'Properties': {
            'Name': loadbalancer_name,
            'HealthCheckIntervalSeconds': '10',
            'HealthCheckPath': health_check_path,
            'HealthCheckPort': health_check_port,
            'HealthCheckProtocol': health_check_protocol,
            'HealthCheckTimeoutSeconds': '5',
            'HealthyThresholdCount': '2',
            'Port': configuration['HTTPPort'],
            'Protocol': 'HTTP',
            'UnhealthyThresholdCount': '2',
            'VpcId': account_info.VpcID,  # TODO: support multiple VPCs
            'Tags': tags,
            'TargetGroupAttributes': [{'Key': 'deregistration_delay.timeout_seconds', 'Value': '60'}]
        }
    }
    resource_names = set([lb_name, target_group_name])
    for i, listener in enumerate(listeners):
        if i == 0:
            suffix = ''
        else:
            suffix = str(i + 1)
        resource_name = lb_name + 'Listener' + suffix
        definition['Resources'][resource_name] = listener
        resource_names.add(resource_name)
    for key, val in configuration.items():
        # overwrite any specified properties, but only properties which were defined by us already
        for res in resource_names:
            if key in definition['Resources'][res]['Properties'] and key not in SENZA_PROPERTIES:
                definition['Resources'][res]['Properties'][key] = val
    return definition
