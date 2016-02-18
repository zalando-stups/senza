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

    asg_properties = definition["Resources"][asg_name]["Properties"]

    if "OperatorTopicId" in info:
        asg_properties["NotificationConfiguration"] = {
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
            asg_properties["LoadBalancerNames"] = [{"Ref": configuration["ElasticLoadBalancer"]}]
        elif isinstance(configuration["ElasticLoadBalancer"], list):
            asg_properties["LoadBalancerNames"] = [{'Ref': ref} for ref in configuration["ElasticLoadBalancer"]]
        # use ELB health check by default
        default_health_check_type = 'ELB'

    asg_properties['HealthCheckType'] = configuration.get('HealthCheckType', default_health_check_type)
    asg_properties['HealthCheckGracePeriod'] = configuration.get('HealthCheckGracePeriod', 300)

    if "AutoScaling" in configuration:
        as_conf = configuration["AutoScaling"]
        asg_properties["MaxSize"] = as_conf["Maximum"]
        asg_properties["MinSize"] = as_conf["Minimum"]
        asg_properties["DesiredCapacity"] = max(int(as_conf["Minimum"]), int(as_conf.get('DesiredCapacity', 1)))

        # ScaleUp policy
        definition["Resources"][asg_name + "ScaleUp"] = {
            "Type": "AWS::AutoScaling::ScalingPolicy",
            "Properties": {
                "AdjustmentType": "ChangeInCapacity",
                "ScalingAdjustment": as_conf.get("ScalingAdjustment", 1),
                "Cooldown": as_conf.get("Cooldown", 60),
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
                "ScalingAdjustment": (-1) * as_conf.get("ScalingAdjustment", 1),
                "Cooldown": as_conf.get("Cooldown", 60),
                "AutoScalingGroupName": {
                    "Ref": asg_name
                }
            }
        }

        metric_type = as_conf["MetricType"]
        metricfn = globals().get('metric_{}'.format(metric_type.lower()))
        if not metricfn:
            raise click.UsageError('Auto scaling MetricType "{}" not supported.'.format(metric_type))
        definition = metricfn(asg_name, definition, as_conf, args, info, force)
    else:
        asg_properties["MaxSize"] = 1
        asg_properties["MinSize"] = 1

    return definition


def metric_cpu(asg_name, definition, configuration, args, info, force):
    period = int(configuration.get("Period", 300))
    evaluation_periods = int(configuration.get("EvaluationPeriods", 2))
    statistic = configuration.get("Statistic", "Average")
    if "ScaleUpThreshold" in configuration:
        definition["Resources"][asg_name + "CPUAlarmHigh"] = {
            "Type": "AWS::CloudWatch::Alarm",
            "Properties": {
                "MetricName": "CPUUtilization",
                "Namespace": "AWS/EC2",
                "Period": str(period),
                "EvaluationPeriods": str(evaluation_periods),
                "Statistic": statistic,
                "Threshold": configuration["ScaleUpThreshold"],
                "ComparisonOperator": "GreaterThanThreshold",
                "Dimensions": [
                    {
                        "Name": "AutoScalingGroupName",
                        "Value": {"Ref": asg_name}
                    }
                ],
                "AlarmDescription": "Scale-up if CPU > {}% for {} minutes ({})".format(
                    configuration["ScaleUpThreshold"],
                    (period / 60) * evaluation_periods,
                    statistic
                ),
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
                "Period": str(period),
                "EvaluationPeriods": str(evaluation_periods),
                "Statistic": statistic,
                "Threshold": configuration["ScaleDownThreshold"],
                "ComparisonOperator": "LessThanThreshold",
                "Dimensions": [
                    {
                        "Name": "AutoScalingGroupName",
                        "Value": {"Ref": asg_name}
                    }
                ],
                "AlarmDescription": "Scale-down if CPU < {}% for {} minutes ({})".format(
                    configuration["ScaleDownThreshold"],
                    (period / 60) * evaluation_periods,
                    statistic
                ),
                "AlarmActions": [
                    {"Ref": asg_name + "ScaleDown"}
                ]
            }
        }

    return definition
