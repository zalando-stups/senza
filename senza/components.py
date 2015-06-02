import json
import textwrap
import urllib
import boto.ec2
import boto.iam
import boto.route53
import boto.vpc
import click
import pierone.api
import pystache
import yaml

from .aws import get_security_group, find_ssl_certificate_arn, resolve_topic_arn
from .docker import docker_image_exists
from .utils import named_value, ensure_keys


def evaluate_template(template, info, components, args):
    data = {"SenzaInfo": info,
            "SenzaComponents": components,
            "Arguments": args}
    result = pystache.render(template, data)
    return result


def component_iam_role(definition, configuration, args, info, force):
    definition = ensure_keys(definition, "Resources")
    role_name = configuration['Name']
    definition['Resources'][role_name] = {
        'Type': 'AWS::IAM::Role',
        'Properties': {
            "AssumeRolePolicyDocument": configuration.get('AssumeRolePolicyDocument', {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": ["ec2.amazonaws.com"]
                        },
                        "Action": ["sts:AssumeRole"]
                    }
                ]
            }),
            'Path': configuration.get('Path', '/'),
            'Policies': configuration.get('Policies', []) + get_merged_policies(
                configuration.get('MergePoliciesFromIamRoles', []), args.region)
        }
    }
    return definition


def component_basic_configuration(definition, configuration, args, info, force):
    # add info as mappings
    # http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/mappings-section-structure.html
    definition = ensure_keys(definition, "Mappings", "Senza", "Info")
    definition["Mappings"]["Senza"]["Info"] = info

    # define parameters
    # http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/parameters-section-structure.html
    if "Parameters" in info:
        definition = ensure_keys(definition, "Parameters")
        default_parameter = {
            "Type": "String"
        }
        for parameter in info["Parameters"]:
            name, value = named_value(parameter)
            value_default = default_parameter.copy()
            value_default.update(value)
            definition["Parameters"][name] = value_default

    if 'Description' not in definition:
        # set some sane default stack description
        definition['Description'] = get_default_description(info, args)

    # ServerSubnets
    if "ServerSubnets" in configuration:
        for region, subnets in configuration["ServerSubnets"].items():
            definition = ensure_keys(definition, "Mappings", "ServerSubnets", region)
            definition["Mappings"]["ServerSubnets"][region]["Subnets"] = subnets

    # LoadBalancerSubnets
    if "LoadBalancerSubnets" in configuration:
        for region, subnets in configuration["LoadBalancerSubnets"].items():
            definition = ensure_keys(definition, "Mappings", "LoadBalancerSubnets", region)
            definition["Mappings"]["LoadBalancerSubnets"][region]["Subnets"] = subnets

    # Images
    if "Images" in configuration:
        for name, image in configuration["Images"].items():
            for region, ami in image.items():
                definition = ensure_keys(definition, "Mappings", "Images", region, name)
                definition["Mappings"]["Images"][region][name] = ami

    return definition


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
    server_subnets = []
    lb_subnets = []
    for subnet in vpc_conn.get_all_subnets():
        name = subnet.tags.get('Name', '')
        if 'dmz' in name:
            lb_subnets.append(subnet.id)
        else:
            server_subnets.append(subnet.id)

    if not lb_subnets:
        # no DMZ subnets were found, just use the same set for both LB and instances
        lb_subnets = server_subnets

    configuration = ensure_keys(configuration, "ServerSubnets", args.region)
    configuration["ServerSubnets"][args.region] = server_subnets

    configuration = ensure_keys(configuration, "LoadBalancerSubnets", args.region)
    configuration["LoadBalancerSubnets"][args.region] = lb_subnets

    most_recent_image = find_taupage_image(args.region)
    configuration = ensure_keys(configuration, "Images", 'LatestTaupageImage', args.region)
    configuration["Images"]['LatestTaupageImage'][args.region] = most_recent_image.id

    component_basic_configuration(definition, configuration, args, info, force)

    return definition


def component_auto_scaling_group_metric_cpu(asg_name, definition, configuration, args, info, force):
    if "ScaleUpThreshold" in configuration:
        definition["Resources"][asg_name + "CPUAlarmHigh"] = {
            "Type": "AWS::CloudWatch::Alarm",
            "Properties": {
                "MetricName": "CPUUtilization",
                "Namespace": "AWS/EC2",
                "Period": "300",
                "EvaluationPeriods": "2",
                "Statistic": "Average",
                "Threshold": configuration["ScaleUpThreshold"],
                "ComparisonOperator": "GreaterThanThreshold",
                "Dimensions": [
                    {
                        "Name": "AutoScalingGroupName",
                        "Value": {"Ref": asg_name}
                    }
                ],
                "AlarmDescription": "Scale-up if CPU > {0}% for 10 minutes".format(configuration["ScaleUpThreshold"]),
                "AlarmActions": [
                    {"Ref": asg_name + "ScaleUp"}
                ]
            }
        }

    if "ScaleDownThreshold" in configuration:
        definition["Resources"][asg_name + "CPUAlarmLow"] = {
            "Type": "AWS::CloudWatch::Alarm",
            "Properties": {
                "MetricName": "CPUUtilization",
                "Namespace": "AWS/EC2",
                "Period": "300",
                "EvaluationPeriods": "2",
                "Statistic": "Average",
                "Threshold": configuration["ScaleDownThreshold"],
                "ComparisonOperator": "LessThanThreshold",
                "Dimensions": [
                    {
                        "Name": "AutoScalingGroupName",
                        "Value": {"Ref": asg_name}
                    }
                ],
                "AlarmDescription": "Scale-down if CPU < {0}% for 10 minutes".format(
                    configuration["ScaleDownThreshold"]),
                "AlarmActions": [
                    {"Ref": asg_name + "ScaleDown"}
                ]
            }
        }

    return definition


def get_merged_policies(roles: list, region: str):
    iam = boto.iam.connect_to_region(region)
    policies = []
    for role in roles:
        policy_names = iam.list_role_policies(role)
        for policy_name in policy_names['list_role_policies_response']['list_role_policies_result']['policy_names']:
            policy = iam.get_role_policy(role, policy_name)['get_role_policy_response']['get_role_policy_result']
            document = urllib.parse.unquote(policy['policy_document'])
            policies.append({'PolicyName': policy_name,
                             'PolicyDocument': json.loads(document)})
    return policies


def component_auto_scaling_group(definition, configuration, args, info, force):
    definition = ensure_keys(definition, "Resources")

    # launch configuration
    config_name = configuration["Name"] + "Config"
    definition["Resources"][config_name] = {
        "Type": "AWS::AutoScaling::LaunchConfiguration",
        "Properties": {
            "InstanceType": configuration["InstanceType"],
            "ImageId": {"Fn::FindInMap": ["Images", {"Ref": "AWS::Region"}, configuration["Image"]]},
            "AssociatePublicIpAddress": configuration.get('AssociatePublicIpAddress', False),
            "EbsOptimized": configuration.get('EbsOptimized', False)
        }
    }

    if 'BlockDeviceMappings' in configuration:
        definition['Resources'][config_name]['Properties']['BlockDeviceMappings'] = configuration['BlockDeviceMappings']

    if "IamInstanceProfile" in configuration:
        definition["Resources"][config_name]["Properties"]["IamInstanceProfile"] = configuration["IamInstanceProfile"]

    if 'IamRoles' in configuration:
        logical_id = configuration['Name'] + 'InstanceProfile'
        roles = configuration['IamRoles']
        if len(roles) > 1:
            for role in roles:
                if isinstance(role, dict):
                    raise click.UsageError('Cannot merge policies of Cloud Formation references ({"Ref": ".."}): ' +
                                           'You can use at most one IAM role with "Ref".')
            logical_role_id = configuration['Name'] + 'Role'
            definition['Resources'][logical_role_id] = {
                'Type': 'AWS::IAM::Role',
                'Properties': {
                    "AssumeRolePolicyDocument": {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {
                                    "Service": ["ec2.amazonaws.com"]
                                },
                                "Action": ["sts:AssumeRole"]
                            }
                        ]
                    },
                    'Path': '/',
                    'Policies': get_merged_policies(roles, args.region)
                }
            }
            instance_profile_roles = [{'Ref': logical_role_id}]
        else:
            instance_profile_roles = roles
        definition['Resources'][logical_id] = {
            'Type': 'AWS::IAM::InstanceProfile',
            'Properties': {
                'Path': '/',
                'Roles': instance_profile_roles
            }
        }
        definition["Resources"][config_name]["Properties"]["IamInstanceProfile"] = {'Ref': logical_id}

    if "SecurityGroups" in configuration:
        definition["Resources"][config_name]["Properties"]["SecurityGroups"] = \
            resolve_security_groups(configuration["SecurityGroups"], args.region)

    if "UserData" in configuration:
        definition["Resources"][config_name]["Properties"]["UserData"] = {
            "Fn::Base64": configuration["UserData"]
        }

    # auto scaling group
    asg_name = configuration["Name"]
    definition["Resources"][asg_name] = {
        "Type": "AWS::AutoScaling::AutoScalingGroup",
        # wait up to 15 minutes to get a signal from at least one server that it booted
        "CreationPolicy": {
            "ResourceSignal": {
                "Count": "1",
                "Timeout": "PT15M"
            }
        },
        "Properties": {
            # for our operator some notifications
            "LaunchConfigurationName": {"Ref": config_name},
            "VPCZoneIdentifier": {"Fn::FindInMap": ["ServerSubnets", {"Ref": "AWS::Region"}, "Subnets"]},
            "AvailabilityZones": {"Fn::GetAZs": ""},
            "Tags": [
                # Tag "Name"
                {
                    "Key": "Name",
                    "PropagateAtLaunch": True,
                    "Value": "{0}-{1}".format(info["StackName"], info["StackVersion"])
                },
                # Tag "StackName"
                {
                    "Key": "StackName",
                    "PropagateAtLaunch": True,
                    "Value": info["StackName"],
                },
                # Tag "StackVersion"
                {
                    "Key": "StackVersion",
                    "PropagateAtLaunch": True,
                    "Value": info["StackVersion"]
                }
            ]
        }
    }

    if "OperatorTopicId" in info:
        definition["Resources"][asg_name]["Properties"]["NotificationConfiguration"] = {
            "NotificationTypes": [
                "autoscaling:EC2_INSTANCE_LAUNCH",
                "autoscaling:EC2_INSTANCE_LAUNCH_ERROR",
                "autoscaling:EC2_INSTANCE_TERMINATE",
                "autoscaling:EC2_INSTANCE_TERMINATE_ERROR"
            ],
            "TopicARN": resolve_topic_arn(args.region, info["OperatorTopicId"])
        }

    default_health_check_type = 'EC2'

    if "ElasticLoadBalancer" in configuration:
        definition["Resources"][asg_name]["Properties"]["LoadBalancerNames"] = [
            {"Ref": configuration["ElasticLoadBalancer"]}]
        # use ELB health check by default
        default_health_check_type = 'ELB'

    definition["Resources"][asg_name]['Properties']['HealthCheckType'] = \
        configuration.get('HealthCheckType', default_health_check_type)
    definition["Resources"][asg_name]['Properties']['HealthCheckGracePeriod'] = \
        configuration.get('HealthCheckGracePeriod', 300)

    if "AutoScaling" in configuration:
        definition["Resources"][asg_name]["Properties"]["MaxSize"] = configuration["AutoScaling"]["Maximum"]
        definition["Resources"][asg_name]["Properties"]["MinSize"] = configuration["AutoScaling"]["Minimum"]

        # ScaleUp policy
        definition["Resources"][asg_name + "ScaleUp"] = {
            "Type": "AWS::AutoScaling::ScalingPolicy",
            "Properties": {
                "AdjustmentType": "ChangeInCapacity",
                "ScalingAdjustment": "1",
                "Cooldown": "60",
                "AutoScalingGroupName": {
                    "Ref": asg_name
                }
            }
        }

        # ScaleDown policy
        definition["Resources"][asg_name + "ScaleDown"] = {
            "Type": "AWS::AutoScaling::ScalingPolicy",
            "Properties": {
                "AdjustmentType": "ChangeInCapacity",
                "ScalingAdjustment": "-1",
                "Cooldown": "60",
                "AutoScalingGroupName": {
                    "Ref": asg_name
                }
            }
        }

        metricfn = ASG_METRICS[configuration["AutoScaling"]["MetricType"]]
        definition = metricfn(asg_name, definition, configuration["AutoScaling"], args, info, force)
    else:
        definition["Resources"][asg_name]["Properties"]["MaxSize"] = 1
        definition["Resources"][asg_name]["Properties"]["MinSize"] = 1

    return definition


def check_docker_image_exists(docker_image: pierone.api.DockerImage):
    if 'pierone' in docker_image.registry:
        try:
            exists = pierone.api.image_exists('pierone', docker_image)
        except pierone.api.Unauthorized:
            msg = textwrap.dedent('''
            Unauthorized: Cannot check whether Docker image "{}" exists in Pier One Docker registry.
            Please generate a "pierone" OAuth access token using "pierone login".
            Alternatively you can skip this check using the "--force" option.
            '''.format(docker_image)).strip()
            raise click.UsageError(msg)

    else:
        exists = docker_image_exists(str(docker_image))
    if not exists:
        raise click.UsageError('Docker image "{}" does not exist'.format(docker_image))


def component_taupage_auto_scaling_group(definition, configuration, args, info, force):
    # inherit from the normal auto scaling group but discourage user info and replace with a Taupage config
    if 'Image' not in configuration:
        configuration['Image'] = 'LatestTaupageImage'
    definition = component_auto_scaling_group(definition, configuration, args, info, force)

    taupage_config = configuration['TaupageConfig']

    if 'notify_cfn' not in taupage_config:
        taupage_config['notify_cfn'] = {'stack': '{}-{}'.format(info["StackName"], info["StackVersion"]),
                                        'resource': configuration['Name']}

    if 'application_id' not in taupage_config:
        taupage_config['application_id'] = info['StackName']

    if 'application_version' not in taupage_config:
        taupage_config['application_version'] = info['StackVersion']

    runtime = taupage_config.get('runtime')
    if runtime != 'Docker':
        raise click.UsageError('Taupage only supports the "Docker" runtime currently')

    source = taupage_config.get('source')
    if not source:
        raise click.UsageError('The "source" property of TaupageConfig must be specified')

    source = evaluate_template(source, info, [], args)

    docker_image = pierone.api.DockerImage.parse(source)

    if not force and docker_image.registry:
        check_docker_image_exists(docker_image)

    userdata = "#taupage-ami-config\n" + yaml.dump(taupage_config, default_flow_style=False)

    config_name = configuration["Name"] + "Config"
    ensure_keys(definition, "Resources", config_name, "Properties", "UserData")
    definition["Resources"][config_name]["Properties"]["UserData"]["Fn::Base64"] = userdata

    return definition


def component_load_balancer(definition, configuration, args, info, force):
    lb_name = configuration["Name"]

    # domains pointing to the load balancer
    main_zone = None
    if "Domains" in configuration:
        for name, domain in configuration["Domains"].items():
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
                "Target": "HTTP:{0}{1}".format(configuration["HTTPPort"],
                                               "/ui/" if "HealthCheckPath" not in configuration else configuration[
                                                   "HealthCheckPath"])
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
            "LoadBalancerName": "{0}-{1}".format(info["StackName"], info["StackVersion"]),
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


def get_default_zone(region):
    dns_conn = boto.route53.connect_to_region(region)
    zones = dns_conn.get_zones()
    domains = sorted([zone.name.rstrip('.') for zone in zones])
    if not domains:
        raise Exception('No Route53 hosted zone found')
    return domains[0]


def component_weighted_dns_load_balancer(definition, configuration, args, info, force):
    if 'Domains' not in configuration:

        if 'MainDomain' in configuration:
            main_domain = configuration['MainDomain']
            main_subdomain, main_zone = main_domain.split('.', 1)
        else:
            main_zone = get_default_zone(args.region)
            main_subdomain = info['StackName']

        if 'VersionDomain' in configuration:
            version_domain = configuration['VersionDomain']
            version_subdomain, version_zone = version_domain.split('.', 1)
        else:
            version_zone = get_default_zone(args.region)
            version_subdomain = '{}-{}'.format(info['StackName'], info['StackVersion'])

        configuration['Domains'] = {'MainDomain': {'Type': 'weighted',
                                                   'Zone': main_zone,
                                                   'Subdomain': main_subdomain},
                                    'VersionDomain': {'Type': 'standalone',
                                                      'Zone': version_zone,
                                                      'Subdomain': version_subdomain}}
    return component_load_balancer(definition, configuration, args, info, force)


def get_default_description(info, args):
    return '{} ({})'.format(info['StackName'].title().replace('-', ' '), format_params(args))


def resolve_security_groups(security_groups: list, region: str):
    result = []
    for id_or_name in security_groups:
        if id_or_name.startswith('sg-'):
            result.append(id_or_name)
        else:
            sg = get_security_group(region, id_or_name)
            if not sg:
                raise ValueError('Security Group "{}" does not exist'.format(id_or_name))
            result.append(sg.id)

    return result


def format_params(args):
    items = [(key, val) for key, val in args.__dict__.items() if key not in ('region', 'version')]
    return ', '.join(['{}: {}'.format(key, val) for key, val in items])


ASG_METRICS = {
    "CPU": component_auto_scaling_group_metric_cpu
}
