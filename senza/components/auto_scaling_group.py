import click
import re
from senza.aws import resolve_security_groups, resolve_topic_arn, resolve_referenced_resource
from senza.utils import ensure_keys
from senza.components.iam_role import get_merged_policies

# properties evaluated by Senza
SENZA_PROPERTIES = frozenset(['SecurityGroups', 'Tags'])

# additional CF properties which can be overwritten
ADDITIONAL_PROPERTIES = {
    'AWS::AutoScaling::LaunchConfiguration': frozenset(['BlockDeviceMappings', 'IamInstanceProfile', 'SpotPrice']),
    'AWS::AutoScaling::AutoScalingGroup': frozenset(['MetricsCollection', 'TargetGroupARNs',
                                                     'TerminationPolicies', 'PlacementGroup'])
}


def create_autoscaling_policy(asg_name, asg_scale_name, asg_scale_adjustment, asg_scale_cooldown, definition):
    if asg_scale_name not in definition["Resources"]:
        scaling_policy_def = {
            "Type": "AWS::AutoScaling::ScalingPolicy",
            "Properties": {
                "AdjustmentType": "ChangeInCapacity",
                "ScalingAdjustment": str(asg_scale_adjustment),
                "Cooldown": str(asg_scale_cooldown),
                "AutoScalingGroupName": {
                    "Ref": asg_name
                }
            }
        }
    else:
        scaling_policy_def = definition["Resources"][asg_scale_name]
        if not scaling_policy_def["Properties"]["AutoScalingGroupName"]["Ref"] == asg_name:
            raise click.UsageError('Specified ScalingPolicy {} does not reference the '
                                   'autoscaling group {}'.format(asg_scale_name, asg_name))

    return scaling_policy_def


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
        elif isinstance(roles[0], dict):
            instance_profile_roles = [resolve_referenced_resource(roles[0], args.region)]
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
    asg_success = ["1", "PT15M"]
    if "AutoScaling" in configuration:
        if "SuccessRequires" in configuration["AutoScaling"]:
            asg_success = normalize_asg_success(configuration["AutoScaling"]["SuccessRequires"])

    tags = [
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

    if "Tags" in configuration:
        for tag in configuration["Tags"]:
            tags.append({
                "Key": tag["Key"],
                "PropagateAtLaunch": True,
                "Value": tag["Value"]
            })

    definition["Resources"][asg_name] = {
        "Type": "AWS::AutoScaling::AutoScalingGroup",
        # wait to get a signal from an amount of servers to signal that it booted
        "CreationPolicy": {
            "ResourceSignal": {
                "Count": asg_success[0],
                "Timeout": asg_success[1]
            }
        },
        "Properties": {
            # for our operator some notifications
            "LaunchConfigurationName": {"Ref": config_name},
            "VPCZoneIdentifier": {"Fn::FindInMap": ["ServerSubnets", {"Ref": "AWS::Region"}, "Subnets"]},
            "Tags": tags
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
    if "ElasticLoadBalancerV2" in configuration:
        if isinstance(configuration["ElasticLoadBalancerV2"], str):
            asg_properties["TargetGroupARNs"] = [{"Ref": configuration["ElasticLoadBalancerV2"] + 'TargetGroup'}]
        elif isinstance(configuration["ElasticLoadBalancerV2"], list):
            asg_properties["TargetGroupARNs"] = [
                {'Ref': ref} for ref in configuration["ElasticLoadBalancerV2"] + 'TargetGroup'
            ]
        # use ELB health check by default
        default_health_check_type = 'ELB'

    asg_properties['HealthCheckType'] = configuration.get('HealthCheckType', default_health_check_type)
    asg_properties['HealthCheckGracePeriod'] = configuration.get('HealthCheckGracePeriod', 300)

    if "AutoScaling" in configuration:
        as_conf = configuration["AutoScaling"]
        asg_properties["MaxSize"] = as_conf["Maximum"]
        asg_properties["MinSize"] = as_conf["Minimum"]
        asg_properties["DesiredCapacity"] = max(int(as_conf["Minimum"]), int(as_conf.get('DesiredCapacity', 1)))

        default_scaling_adjustment = as_conf.get("ScalingAdjustment", 1)
        default_cooldown = as_conf.get("Cooldown", "60")

        # ScaleUp policy
        scale_up_name = asg_name + "ScaleUp"
        scale_up_adjustment = int(
            as_conf.get("ScaleUpAdjustment", default_scaling_adjustment))
        scale_up_cooldown = as_conf.get(
            "ScaleUpCooldown", default_cooldown)

        definition["Resources"][scale_up_name] = create_autoscaling_policy(
            asg_name, scale_up_name, scale_up_adjustment, scale_up_cooldown, definition)

        # ScaleDown policy
        scale_down_name = asg_name + "ScaleDown"
        scale_down_adjustment = (-1) * int(
            as_conf.get("ScaleDownAdjustment", default_scaling_adjustment))
        scale_down_cooldown = as_conf.get(
            "ScaleDownCooldown", default_cooldown)

        definition["Resources"][scale_down_name] = create_autoscaling_policy(
            asg_name, scale_down_name, scale_down_adjustment, scale_down_cooldown, definition)

        if "MetricType" in as_conf:
            metric_type = as_conf["MetricType"]
            metricfns = {
                "CPU": metric_cpu,
                "NetworkIn": metric_network,
                "NetworkOut": metric_network
            }
            # lowercase cpu is an acceptable metric, be compatible
            if metric_type.lower() not in map(lambda t: t.lower(), metricfns.keys()):
                raise click.UsageError('Auto scaling MetricType "{}" not supported.'.format(metric_type))
            metricfn = metricfns[metric_type]
            definition = metricfn(asg_name, definition, as_conf, args, info, force)
    else:
        asg_properties["MaxSize"] = 1
        asg_properties["MinSize"] = 1

    for res in (config_name, asg_name):
        props = definition['Resources'][res]['Properties']
        additional_cf_properties = ADDITIONAL_PROPERTIES.get(definition['Resources'][res]['Type'])
        properties_allowed_to_overwrite = (set(props.keys()) - SENZA_PROPERTIES) | additional_cf_properties
        for key in properties_allowed_to_overwrite:
            if key in configuration:
                props[key] = configuration[key]

    return definition

duration_regex = r'^(?:\d+[hH])?(?:\d+[mM])?(?:\d+[sS])?$'
duration_split_regex = r'(\d+[hHmMsS])'


def to_iso8601_duration(duration):
    if duration and re.match(duration_regex, duration):
        durations = [d.upper() for d in re.split(duration_split_regex, duration)]
        return "PT" + "".join(durations)
    else:
        raise click.UsageError("Unknown duration {}. Use something like 15m.".format(duration))


def normalize_asg_success(success):
    count = "1"
    duration = "PT15M"

    # if it's falsy, return defaults
    if not success:
        return [count, duration]

    # if it's int, use as instance count
    if isinstance(success, int):
        return [str(success), duration]

    try:
        # try to parse as int
        count = int(success)
        # if it works, use as instance count
        return [success, duration]
    except ValueError:
        # ok did not work, try to parse
        if "within" in success:
            instance, time = success.split("within")
            return [instance.strip(), to_iso8601_duration(time.strip())]
        else:
            msg = 'Unknown ASG success requirement "{}". Use something like "1 within 10m".'
            raise click.UsageError(msg.format(success))


def normalize_network_threshold(threshold):
    unit = "Bytes"
    if threshold is None:
        return []
    if isinstance(threshold, int):
        return [str(threshold), unit]
    amount = 1024
    shortcuts = {
        "B": "Bytes",
        "KB": "Kilobytes",
        "MB": "Megabytes",
        "GB": "Gigabytes",
        "TB": "Terabytes"
    }
    try:
        # if someone write just Threshold: 10
        amount = int(threshold)
        return [threshold, unit]
    except ValueError:
        # check if there is a space as if somebody wrote Threshold: 20 GB
        if " " in threshold:
            # okay, so split it
            amount, unit = threshold.split()
            if unit in shortcuts:
                unit = shortcuts[unit]
            allowed_units = shortcuts.values()
            if unit not in allowed_units:
                raise click.UsageError("Network threshold unit must be one of {}".format(list(allowed_units)))
        else:
            raise click.UsageError('Unknown network threshold "{}". Use something like "20 GB".'.format(threshold))
    return [amount, unit]


def metric_network(asg_name, definition, configuration, args, info, force):
    period = int(configuration.get("Period", 300))
    evaluation_periods = int(configuration.get("EvaluationPeriods", 2))
    statistic = configuration.get("Statistic", "Average")
    scale_up_threshold = normalize_network_threshold(configuration["ScaleUpThreshold"])
    scale_down_threshold = normalize_network_threshold(configuration["ScaleDownThreshold"])

    if "ScaleUpThreshold" in configuration:
        definition["Resources"][asg_name + "NetworkAlarmHigh"] = {
            "Type": "AWS::CloudWatch::Alarm",
            "Properties": {
                "MetricName": configuration["MetricType"],
                "Namespace": "AWS/EC2",
                "Period": str(period),
                "Threshold": scale_up_threshold[0],
                "Unit": scale_up_threshold[1],
                "EvaluationPeriods": str(evaluation_periods),
                "Statistic": statistic,
                "ComparisonOperator": "GreaterThanThreshold",
                "Dimensions": [
                    {
                        "Name": "AutoScalingGroupName",
                        "Value": {"Ref": asg_name}
                    }
                ],
                "AlarmDescription": "Scale-up if {} > {} {} for {} minutes ({})".format(
                    configuration["MetricType"],
                    scale_up_threshold[0],
                    scale_up_threshold[1],
                    (period / 60) * evaluation_periods,
                    statistic
                ),
                "AlarmActions": [
                    {"Ref": asg_name + "ScaleUp"}
                ]
            }
        }

    if "ScaleDownThreshold" in configuration:
        definition["Resources"][asg_name + "NetworkAlarmLow"] = {
            "Type": "AWS::CloudWatch::Alarm",
            "Properties": {
                "MetricName": configuration["MetricType"],
                "Namespace": "AWS/EC2",
                "Threshold": scale_down_threshold[0],
                "Unit": scale_down_threshold[1],
                "Period": str(period),
                "EvaluationPeriods": str(evaluation_periods),
                "Statistic": statistic,
                "ComparisonOperator": "LessThanThreshold",
                "Dimensions": [
                    {
                        "Name": "AutoScalingGroupName",
                        "Value": {"Ref": asg_name}
                    }
                ],
                "AlarmDescription": "Scale-down if {} < {} {} for {} minutes ({})".format(
                    configuration["MetricType"],
                    scale_down_threshold[0],
                    scale_down_threshold[1],
                    (period / 60) * evaluation_periods,
                    statistic
                ),
                "AlarmActions": [
                    {"Ref": asg_name + "ScaleDown"}
                ]
            }
        }

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
