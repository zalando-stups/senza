#!/usr/bin/env python3
import calendar
import configparser
import os

import sys
import json
from boto.exception import BotoServerError
import click
from clickclick import AliasedGroup, Action
from clickclick.console import print_table

import yaml
import pystache
import boto.cloudformation
import boto.vpc
import boto.ec2
import boto.iam

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


def named_value(d):
    return next(iter(d.items()))


def ensure_keys(dict, *keys):
    if len(keys) == 0:
        return dict
    else:
        first, rest = keys[0], keys[1:]
        if first not in dict:
            dict[first] = {}
        dict[first] = ensure_keys(dict[first], *rest)
        return dict


class DefinitionParamType(click.ParamType):
    name = 'definition'

    def convert(self, value, param, ctx):
        if isinstance(value, str):
            try:
                with open(value, 'r') as fd:
                    data = yaml.safe_load(fd)
            except FileNotFoundError:
                self.fail('"{}" not found'.format(value), param, ctx)
        else:
            data = value
        for key in 'SenzaInfo', 'SenzaComponents':
            if key not in data:
                self.fail('"{}" entry is missing in YAML file "{}"'.format(key, value), param, ctx)
        return data


DEFINITION = DefinitionParamType()


# all components
def component_basic_configuration(definition, configuration, args, info):
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


def component_stups_auto_configuration(definition, configuration, args, info):
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

    # ServerSubnets
    vpc_conn = boto.vpc.connect_to_region(args.region)
    server_subnets = []
    lb_subnets = []
    for subnet in vpc_conn.get_all_subnets():
        name = subnet.tags.get('Name', '')
        if 'dmz' in name:
            lb_subnets.append(subnet.id)
        else:
            server_subnets.append(subnet.id)
    definition = ensure_keys(definition, "Mappings", "ServerSubnets", args.region)
    definition["Mappings"]["ServerSubnets"][args.region]["Subnets"] = server_subnets

    definition = ensure_keys(definition, "Mappings", "LoadBalancerSubnets", args.region)
    definition["Mappings"]["LoadBalancerSubnets"][args.region]["Subnets"] = lb_subnets

    # Images
    filters = {'name': '*Taupage-AMI-*',
               'is_public': 'false',
               'state': 'available',
               'root_device_type': 'ebs'}
    ec2_conn = boto.ec2.connect_to_region(args.region)
    images = ec2_conn.get_all_images(filters=filters)
    if not images:
        raise Exception('No Taupage AMI found')
    most_recent_image = sorted(images, key=lambda i: i.name)[-1]
    definition = ensure_keys(definition, "Mappings", "Images", args.region, 'LatestTaupageImage')
    definition["Mappings"]["Images"][args.region]['LatestTaupageImage'] = most_recent_image.id

    return definition


def component_auto_scaling_group_metric_cpu(asg_name, definition, configuration, args, info):
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


ASG_METRICS = {
    "CPU": component_auto_scaling_group_metric_cpu
}


def component_auto_scaling_group(definition, configuration, args, info):
    definition = ensure_keys(definition, "Resources")

    # launch configuration
    config_name = configuration["Name"] + "Config"
    definition["Resources"][config_name] = {
        "Type": "AWS::AutoScaling::LaunchConfiguration",
        "Properties": {
            "InstanceType": configuration["InstanceType"],
            "ImageId": {"Fn::FindInMap": ["Images", {"Ref": "AWS::Region"}, configuration["Image"]]},
            "AssociatePublicIpAddress": False
        }
    }

    if "IamInstanceProfile" in configuration:
        definition["Resources"][config_name]["Properties"]["IamInstanceProfile"] = configuration["IamInstanceProfile"]

    if "SecurityGroups" in configuration:
        definition["Resources"][config_name]["Properties"]["SecurityGroups"] = configuration["SecurityGroups"]

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
            "TopicARN": info["OperatorTopicId"]
        }

    if "ElasticLoadBalancer" in configuration:
        definition["Resources"][asg_name]["Properties"]["LoadBalancerNames"] = [
            {"Ref": configuration["ElasticLoadBalancer"]}]

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
        definition = metricfn(asg_name, definition, configuration["AutoScaling"], args, info)
    else:
        definition["Resources"][asg_name]["Properties"]["MaxSize"] = 1
        definition["Resources"][asg_name]["Properties"]["MinSize"] = 1

    return definition


def component_taupage_auto_scaling_group(definition, configuration, args, info):
    # inherit from the normal auto scaling group but discourage user info and replace with a Taupage config
    if 'Image' not in configuration:
        configuration['Image'] = 'LatestTaupageImage'
    definition = component_auto_scaling_group(definition, configuration, args, info)

    taupage_config = configuration['TaupageConfig']

    if 'notify_cfn' not in taupage_config:
        taupage_config['notify_cfn'] = {'stack': '{}-{}'.format(info["StackName"], info["StackVersion"]),
                                        'resource': configuration['Name']}

    userdata = "#zalando-ami-config\n" + yaml.dump(taupage_config, default_flow_style=False)

    config_name = configuration["Name"] + "Config"
    ensure_keys(definition, "Resources", config_name, "Properties", "UserData")
    definition["Resources"][config_name]["Properties"]["UserData"]["Fn::Base64"] = userdata

    return definition


def find_ssl_certificate_arn(region, pattern):
    '''Find the a matching SSL cert and return its ARN'''
    iam_conn = boto.iam.connect_to_region(region)
    response = iam_conn.list_server_certs()
    response = response['list_server_certificates_response']
    certs = response['list_server_certificates_result']['server_certificate_metadata_list']
    candidates = set()
    for cert in certs:
        if pattern in cert['server_certificate_name']:
            candidates.add(cert['arn'])
    if candidates:
        # return first match (alphabetically sorted
        return sorted(candidates)[0]
    else:
        return None


def component_load_balancer(definition, configuration, args, info):
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
            "SecurityGroups": [] if "SecurityGroups" not in configuration else configuration["SecurityGroups"],
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


COMPONENTS = {
    "Senza::Configuration": component_basic_configuration,
    "Senza::StupsAutoConfiguration": component_stups_auto_configuration,
    "Senza::AutoScalingGroup": component_auto_scaling_group,
    "Senza::TaupageAutoScalingGroup": component_taupage_auto_scaling_group,
    "Senza::ElasticLoadBalancer": component_load_balancer,
    "Senza::WeightedDnsElasticLoadBalancer": component_load_balancer,
}

BASE_TEMPLATE = {
    "AWSTemplateFormatVersion": "2010-09-09"
}


def evaluate(definition, args):
    # extract Senza* meta information
    info = definition.pop("SenzaInfo")
    info["StackVersion"] = args.version

    components = definition.pop("SenzaComponents")

    # merge base template with definition
    BASE_TEMPLATE.update(definition)
    definition = BASE_TEMPLATE

    # evaluate all components
    for component in components:
        componentname, configuration = named_value(component)
        configuration["Name"] = componentname

        componenttype = configuration["Type"]
        componentfn = COMPONENTS[componenttype]

        definition = componentfn(definition, configuration, args, info)

    # throw executed template to templating engine and provide all information for substitutions
    template_data = definition.copy()
    template_data.update({"SenzaInfo": info,
                          "SenzaComponents": components,
                          "Arguments": args})

    template = yaml.dump(definition, default_flow_style=False)
    definition = pystache.render(template, template_data)

    definition = yaml.load(definition)

    return definition


@click.group(cls=AliasedGroup, context_settings=CONTEXT_SETTINGS)
def cli():
    pass


class TemplateArguments:
    def __init__(self, **kwargs):
        for key, val in kwargs.items():
            setattr(self, key, val)


def is_credentials_expired_error(e: BotoServerError) -> bool:
    return (e.status == 400 and 'request has expired' in e.message.lower()) or \
           (e.status == 403 and 'security token included in the request is expired' in e.message.lower())


def parse_args(input, region, version, parameter):
    paras = {}
    for i, param in enumerate(input['SenzaInfo'].get('Parameters', [])):
        for key, config in param.items():
            if len(parameter) <= i:
                raise click.UsageError('Missing parameter "{}"'.format(key))
            paras[key] = parameter[i]
    args = TemplateArguments(region=region, version=version, **paras)
    return args


def get_region(region):
    if not region:
        config = configparser.ConfigParser()
        config.read(os.path.expanduser('~/.aws/config'))
        if 'default' in config:
            region = config['default']['region']

    if not region:
        raise click.UsageError('Please specify the AWS region on the command line (--region) or in ~/.aws/config')

    cf = boto.cloudformation.connect_to_region(region)
    if not cf:
        raise click.UsageError('Invalid region "{}"'.format(region))
    return region


@cli.command('list')
@click.option('--region', envvar='AWS_DEFAULT_REGION')
def list_stacks(region):
    '''List Cloud Formation stacks'''
    region = get_region(region)
    cf = boto.cloudformation.connect_to_region(region)
    stacks = cf.list_stacks()
    rows = []
    for stack in stacks:
        rows.append({'Name': stack.stack_name, 'Status': stack.stack_status,
                     'creation_time': calendar.timegm(stack.creation_time.timetuple()),
                     'Description': stack.template_description})

    rows.sort(key=lambda x: x['Name'])

    styles = {
        'DELETE_COMPLETE': {'fg': 'red'},
        'ROLLBACK_COMPLETE': {'fg': 'red'},
        'CREATE_COMPLETE': {'fg': 'green'},
        'CREATE_IN_PROGRESS': {'fg': 'yellow', 'bold': True},
        'DELETE_IN_PROGRESS': {'fg': 'red', 'bold': True},
    }

    titles = {
        'creation_time': 'Created'
    }

    print_table('Name Status creation_time Description'.split(), rows, styles=styles, titles=titles)


@cli.command()
@click.argument('definition', type=DEFINITION)
@click.argument('version')
@click.argument('parameter', nargs=-1)
@click.option('--region', envvar='AWS_DEFAULT_REGION')
def create(definition, region, version, parameter):
    '''Create a new stack'''

    input = definition

    region = get_region(region)
    args = parse_args(input, region, version, parameter)

    data = evaluate(input.copy(), args)
    cfjson = json.dumps(data, sort_keys=True, indent=4)

    stack_name = "{0}-{1}".format(input["SenzaInfo"]["StackName"], version)

    parameters = []
    for name, parameter in data["Parameters"].items():
        parameters.append([name, getattr(args, name)])

    tags = {
        "Name": stack_name,
        "StackName": input["SenzaInfo"]["StackName"],
        "StackVersion": version
    }

    if "OperatorTopicId" in input["SenzaInfo"]:
        topics = [input["SenzaInfo"]["OperatorTopicId"]]
    else:
        topics = None

    cf = boto.cloudformation.connect_to_region(region)
    cf.create_stack(stack_name, template_body=cfjson, parameters=parameters, tags=tags, notification_arns=topics)


@cli.command('print')
@click.argument('definition', type=DEFINITION)
@click.argument('version')
@click.argument('parameter', nargs=-1)
@click.option('--region', envvar='AWS_DEFAULT_REGION')
def print_cfjson(definition, region, version, parameter):
    '''Print the generated Cloud Formation template'''
    input = definition
    region = get_region(region)
    args = parse_args(input, region, version, parameter)
    data = evaluate(input.copy(), args)
    cfjson = json.dumps(data, sort_keys=True, indent=4)

    click.secho(cfjson)


@cli.command()
@click.argument('stack_name')
@click.option('--region', envvar='AWS_DEFAULT_REGION')
def delete(stack_name, region):
    region = get_region(region)
    cf = boto.cloudformation.connect_to_region(region)

    with Action('Deleting Cloud Formation stack {}..'.format(stack_name)):
        cf.delete_stack(stack_name)


def main():
    try:
        cli()
    except BotoServerError as e:
        if is_credentials_expired_error(e):
            sys.stderr.write('AWS credentials have expired. ' +
                             'Use the "mai" command line tool to get a new temporary access key.\n')
            sys.exit(1)
        else:
            raise


if __name__ == "__main__":
    main()
