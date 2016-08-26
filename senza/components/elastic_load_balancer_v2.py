import click
from clickclick import fatal_error
from senza.aws import resolve_security_groups
from senza.components.elastic_load_balancer import get_load_balancer_name

from ..cli import AccountArguments, TemplateArguments
from ..manaus import ClientError
from ..manaus.acm import ACM, ACMCertificate
from ..manaus.iam import IAM, IAMServerCertificate
from ..manaus.route53 import convert_domain_records_to_alias

SENZA_PROPERTIES = frozenset(['Domains', 'HealthCheckPath', 'HealthCheckPort', 'HealthCheckProtocol',
                              'HTTPPort', 'Name', 'SecurityGroups', 'SSLCertificateId', 'Type'])


def get_listeners(lb_name, target_group_name, subdomain, main_zone, configuration,
                  account_info: AccountArguments):
    ssl_cert = configuration.get('SSLCertificateId')

    if ACMCertificate.arn_is_acm_certificate(ssl_cert):
        # check if certificate really exists
        try:
            ACMCertificate.get_by_arn(account_info.Region, ssl_cert)
        except ClientError as e:
            error_msg = e.response['Error']['Message']
            fatal_error(error_msg)
    elif IAMServerCertificate.arn_is_server_certificate(ssl_cert):
        # TODO check if certificate exists
        pass
    elif ssl_cert is not None:
        certificate = IAMServerCertificate.get_by_name(account_info.Region,
                                                       ssl_cert)
        ssl_cert = certificate.arn
    elif main_zone is not None:
        if main_zone:
            iam_pattern = main_zone.lower().rstrip('.').replace('.', '-')
            name = '{sub}.{zone}'.format(sub=subdomain,
                                         zone=main_zone.rstrip('.'))
            acm = ACM(account_info.Region)
            acm_certificates = sorted(acm.get_certificates(domain_name=name),
                                      reverse=True)
        else:
            iam_pattern = ''
            acm_certificates = []
        iam = IAM(account_info.Region)
        iam_certificates = sorted(iam.get_certificates(name=iam_pattern))
        if not iam_certificates:
            # if there are no iam certificates matching the pattern
            # try to use any certificate
            iam_certificates = sorted(iam.get_certificates(), reverse=True)

        # the priority is acm_certificate first and iam_certificate second
        certificates = (acm_certificates +
                        iam_certificates)  # type: List[Union[ACMCertificate, IAMServerCertificate]]
        try:
            certificate = certificates[0]
            ssl_cert = certificate.arn
        except IndexError:
            if main_zone:
                fatal_error('Could not find any matching '
                            'SSL certificate for "{}"'.format(name))
            else:
                fatal_error('Could not find any SSL certificate')
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

        convert_domain_records_to_alias(domain_name)

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

    if configuration.get('NameSuffix'):
        version = '{}-{}'.format(info["StackVersion"],
                                 configuration['NameSuffix'])
        loadbalancer_name = get_load_balancer_name(info["StackName"], version)
        del(configuration['NameSuffix'])
    else:
        loadbalancer_name = get_load_balancer_name(info["StackName"],
                                                   info["StackVersion"])

    loadbalancer_scheme = "internal"
    allowed_loadbalancer_schemes = ("internet-facing", "internal")
    if "Scheme" in configuration:
        loadbalancer_scheme = configuration["Scheme"]
    else:
        configuration["Scheme"] = loadbalancer_scheme

    if loadbalancer_scheme == 'internet-facing':
        click.secho('You are deploying an internet-facing ELB that will be '
                    'publicly accessible! You should have OAUTH2 and HTTPS '
                    'in place!', bold=True, err=True)

    if loadbalancer_scheme not in allowed_loadbalancer_schemes:
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
    for i, listener in enumerate(listeners):
        if i == 0:
            suffix = ''
        else:
            suffix = str(i + 1)
        definition['Resources'][lb_name + 'Listener' + suffix] = listener
    for key, val in configuration.items():
        # overwrite any specified properties, but
        # ignore our special Senza properties as they are not supported by CF
        if key not in SENZA_PROPERTIES:
            definition['Resources'][lb_name]['Properties'][key] = val

    return definition
