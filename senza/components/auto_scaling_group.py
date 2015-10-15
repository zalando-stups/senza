import click

from senza.aws import resolve_security_groups, resolve_topic_arn
from senza.utils import ensure_keys
from senza.components.iam_role import get_merged_policies


def component_auto_scaling_group(definition, configuration, args, info, force, account_info):
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
                    'Policies': get_merged_policies(roles)
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
        if isinstance(configuration["ElasticLoadBalancer"], str):
            definition["Resources"][asg_name]["Properties"]["LoadBalancerNames"] = [
                {"Ref": configuration["ElasticLoadBalancer"]}]
        elif isinstance(configuration["ElasticLoadBalancer"], list):
            definition["Resources"][asg_name]["Properties"]["LoadBalancerNames"] = []
            for ref in configuration["ElasticLoadBalancer"]:
                definition["Resources"][asg_name]["Properties"]["LoadBalancerNames"].append({'Ref': ref})
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

        metric_type = configuration["AutoScaling"]["MetricType"]
        metricfn = globals().get('metric_{}'.format(metric_type.lower()))
        if not metricfn:
            raise click.UsageError('Auto scaling MetricType "{}" not supported.'.format(metric_type))
        definition = metricfn(asg_name, definition, configuration["AutoScaling"], args, info, force)
    else:
        definition["Resources"][asg_name]["Properties"]["MaxSize"] = 1
        definition["Resources"][asg_name]["Properties"]["MinSize"] = 1

    return definition


def metric_cpu(asg_name, definition, configuration, args, info, force):
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
