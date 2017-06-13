import click
from clickclick import fatal_error
from senza.aws import resolve_security_groups
from senza.definitions import AccountArguments
from senza.utils import get_load_balancer_name

from ..cli import TemplateArguments
from ..manaus import ClientError
from ..manaus.acm import ACM, ACMCertificate
from ..manaus.iam import IAM, IAMServerCertificate
from ..manaus.route53 import convert_cname_records_to_alias

SENZA_PROPERTIES = frozenset(['Domains', 'HealthCheckPath', 'HealthCheckPort', 'HealthCheckProtocol',
                              'HTTPPort', 'Name', 'SecurityGroups', 'SSLCertificateId', 'Type'])
ALLOWED_HEALTH_CHECK_PROTOCOLS = frozenset(["HTTP", "TCP", "UDP", "SSL"])
ALLOWED_LOADBALANCER_SCHEMES = frozenset(["internet-facing", "internal"])


def get_ssl_cert(subdomain, main_zone, configuration, account_info: AccountArguments):
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

    return ssl_cert


def get_listeners(configuration):
    return [
        {
            "PolicyNames": [],
            "SSLCertificateId": configuration.get('SSLCertificateId'),
            "Protocol": "HTTPS",
            "InstancePort": configuration["HTTPPort"],
            "LoadBalancerPort": 443
        }
    ]


def resolve_ssl_certificates(listeners, subdomain, main_zone, account_info):
    new_listeners = []
    for listener in listeners:
        if listener.get('Protocol') in ('HTTPS', 'SSL'):
            ssl_cert = get_ssl_cert(subdomain, main_zone, listener, account_info)
            listener['SSLCertificateId'] = ssl_cert
        new_listeners.append(listener)
    return new_listeners


def component_elastic_load_balancer(definition,
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
                                                                      "CanonicalHostedZoneNameID"]},
                                      "DNSName": {"Fn::GetAtt": [lb_name, "DNSName"]}}}
        definition["Resources"][name] = {"Type": "AWS::Route53::RecordSet",
                                         "Properties": properties}

        if domain["Type"] == "weighted":
            definition["Resources"][name]["Properties"]['Weight'] = 0
            definition["Resources"][name]["Properties"]['SetIdentifier'] = "{0}-{1}".format(info["StackName"],
                                                                                            info["StackVersion"])
            subdomain = domain['Subdomain']
            main_zone = domain['Zone']  # type: str

    listeners = configuration.get('Listeners') or get_listeners(configuration)
    listeners = resolve_ssl_certificates(listeners, subdomain, main_zone, account_info)

    health_check_protocol = configuration.get('HealthCheckProtocol') or 'HTTP'

    if health_check_protocol not in ALLOWED_HEALTH_CHECK_PROTOCOLS:
        raise click.UsageError('Protocol "{}" is not supported for LoadBalancer'.format(health_check_protocol))

    health_check_path = configuration.get("HealthCheckPath") or '/health'
    health_check_port = configuration.get("HealthCheckPort") or configuration["HTTPPort"]

    health_check_target = "{0}:{1}{2}".format(health_check_protocol,
                                              health_check_port,
                                              health_check_path)

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

    # load balancer
    definition["Resources"][lb_name] = {
        "Type": "AWS::ElasticLoadBalancing::LoadBalancer",
        "Properties": {
            "Scheme": loadbalancer_scheme,
            "Subnets": {"Fn::FindInMap": [loadbalancer_subnet_map, {"Ref": "AWS::Region"}, "Subnets"]},
            "HealthCheck": {
                "HealthyThreshold": "2",
                "UnhealthyThreshold": "2",
                "Interval": "10",
                "Timeout": "5",
                "Target": health_check_target
            },
            "Listeners": listeners,
            "ConnectionDrainingPolicy": {
                "Enabled": True,
                "Timeout": 60
            },
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
    for key, val in configuration.items():
        # overwrite any specified properties, but
        # ignore our special Senza properties as they are not supported by CF
        if key not in SENZA_PROPERTIES:
            definition['Resources'][lb_name]['Properties'][key] = val

    return definition
