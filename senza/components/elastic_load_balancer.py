
import click

from senza.aws import find_ssl_certificate_arn, resolve_security_groups


def get_load_balancer_name(stack_name: str, stack_version: str):
    '''
    >>> get_load_balancer_name('a', '1')
    'a-1'

    >>> get_load_balancer_name('toolong123456789012345678901234567890', '1')
    'toolong12345678901234567890123-1'
    '''
    # Loadbalancer name cannot exceed 32 characters, try to shorten
    l = 32 - len(stack_version) - 1
    return '{}-{}'.format(stack_name[:l], stack_version)


def component_elastic_load_balancer(definition, configuration, args, info, force):
    lb_name = configuration["Name"]

    # domains pointing to the load balancer
    main_zone = None
    for name, domain in configuration.get('Domains', {}).items():
        definition["Resources"][name] = {
            "Type": "AWS::Route53::RecordSet",
            "Properties": {
                "Type": "CNAME",
                "TTL": 20,
                "ResourceRecords": [
                    {"Fn::GetAtt": [lb_name, "DNSName"]}
                ],
                "Name": "{0}.{1}".format(domain["Subdomain"], domain["Zone"]),
                "HostedZoneName": "{0}.".format(domain["Zone"])
            },
        }

        if domain["Type"] == "weighted":
            definition["Resources"][name]["Properties"]['Weight'] = 0
            definition["Resources"][name]["Properties"]['SetIdentifier'] = "{0}-{1}".format(info["StackName"],
                                                                                            info["StackVersion"])
            main_zone = domain['Zone']

    ssl_cert = configuration.get('SSLCertificateId')

    pattern = None
    if not ssl_cert:
        if main_zone:
            pattern = main_zone.lower().replace('.', '-')
        else:
            pattern = ''
    elif not ssl_cert.startswith('arn:'):
        pattern = ssl_cert

    if pattern is not None:
        ssl_cert = find_ssl_certificate_arn(args.region, pattern)

        if not ssl_cert:
            raise click.UsageError('Could not find any matching SSL certificate for "{}"'.format(pattern))

    health_check_protocol = "HTTP"
    allowed_health_check_protocols = ("HTTP", "TCP", "UDP", "SSL")
    if "HealthCheckProtocol" in configuration:
        health_check_protocol = configuration["HealthCheckProtocol"]

    if health_check_protocol not in allowed_health_check_protocols:
        raise click.UsageError('Protocol "{}" is not supported for LoadBalancer'.format(health_check_protocol))

    health_check_path = "/ui/"
    if "HealthCheckPath" in configuration:
        health_check_path = configuration["HealthCheckPath"]

    health_check_port = configuration["HTTPPort"]
    if "HealthCheckPort" in configuration:
        health_check_port = configuration["HealthCheckPort"]

    health_check_target = "{0}:{1}{2}".format(health_check_protocol, health_check_port, health_check_path)
    loadbalancer_name = get_load_balancer_name(info["StackName"], info["StackVersion"])

    # load balancer
    definition["Resources"][lb_name] = {
        "Type": "AWS::ElasticLoadBalancing::LoadBalancer",
        "Properties": {
            "Scheme": "internet-facing",
            "Subnets": {"Fn::FindInMap": ["LoadBalancerSubnets", {"Ref": "AWS::Region"}, "Subnets"]},
            "HealthCheck": {
                "HealthyThreshold": "2",
                "UnhealthyThreshold": "2",
                "Interval": "10",
                "Timeout": "5",
                "Target": health_check_target
            },
            "Listeners": [
                {
                    "PolicyNames": [],
                    "SSLCertificateId": ssl_cert,
                    "Protocol": "HTTPS",
                    "InstancePort": configuration["HTTPPort"],
                    "LoadBalancerPort": 443
                }
            ],
            "CrossZone": "true",
            "LoadBalancerName": loadbalancer_name,
            "SecurityGroups": resolve_security_groups(configuration["SecurityGroups"], args.region),
            "Tags": [
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
        }
    }

    return definition
