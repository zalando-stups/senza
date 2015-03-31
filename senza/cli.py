#!/usr/bin/env python3

import sys
import argparse
import json

import yaml





# some helpers

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


## all components

def component_basic_configuration(definition, configuration, args, info):
    # add info as mappings
    # http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/mappings-section-structure.html
    definition = ensure_keys(definition, "Mappings", "SenzaInfo")
    definition["Mappings"]["SenzaInfo"].update(info)
    definition["Mappings"]["SenzaInfo"]["StackVersion"] = args.version

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

    # OperatorEMail
    if "OperatorEMail" in configuration:
        definition["Mappings"]["OperatorEMail"] = configuration["OperatorEMail"]

        definition = ensure_keys(definition, "Resources")

        definition["Resources"]["OperatorTopic"] = {
            "Type": "AWS::SNS::Topic",
            "Properties": {
                "Subscription": [{
                                     "Endpoint": {"Ref": "OperatorEMail"},
                                     "Protocol": "email"
                                 }],
                "DisplayName": {
                    "Fn::Join": [
                        " ",
                        [
                            {"Fn::FindInMap": ["SenzaInfo", "StackName"]},
                            {"Fn::FindInMap": ["SenzaInfo", "StackVersion"]}
                        ]
                    ]
                }
            }
        }

    # ServerSubnets
    if "ServerSubnets" in configuration:
        definition = ensure_keys(definition, "Mappings", "ServerSubnets")
        for region, subnets in configuration["ServerSubnets"].items():
            definition["Mappings"]["ServerSubnets"][region] = subnets

    # LoadBalancerSubnets
    if "LoadBalancerSubnets" in configuration:
        definition = ensure_keys(definition, "Mappings", "LoadBalancerSubnets")
        for region, subnets in configuration["LoadBalancerSubnets"].items():
            definition["Mappings"]["LoadBalancerSubnets"][region] = subnets

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
                "ComparisonOperator": "LowerThanThreshold",
                "Dimensions": [
                    {
                        "Name": "AutoScalingGroupName",
                        "Value": {"Ref": asg_name}
                    }
                ],
                "AlarmDescription": "Scale-down if CPU < {0}% for 10 minutes".format(configuration["ScaleDownThreshold"]),
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
            "ImageId": {"Fn::FindInMap": ["Images", configuration["Image"], {"Ref": "AWS::Region"}]},
            "AssociatePublicIpAddress": False
        }
    }

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
            "Tags": [
                # Tag "Name"
                {
                    "Key": "Name",
                    "PropagateAtLaunch": True,
                    "Value": {
                        "Fn::Join": [
                            " ",
                            [
                                {"Fn::FindInMap": ["SenzaInfo", "StackName"]},
                                {"Fn::FindInMap": ["SenzaInfo", "StackVersion"]}
                            ]
                        ]
                    }
                },
                # Tag "StackName"
                {
                    "Key": "StackName",
                    "PropagateAtLaunch": True,
                    "Value": {"Fn::FindInMap": ["SenzaInfo", "StackName"]},
                },
                # Tag "StackVersion"
                {
                    "Key": "StackVersion",
                    "PropagateAtLaunch": True,
                    "Value": {"Fn::FindInMap": ["SenzaInfo", "StackVersion"]}
                }
            ],
            # for our operator some notifications
            "NotificationConfiguration": {
                "NotificationTypes": [
                    "autoscaling:EC2_INSTANCE_LAUNCH",
                    "autoscaling:EC2_INSTANCE_LAUNCH_ERROR",
                    "autoscaling:EC2_INSTANCE_TERMINATE",
                    "autoscaling:EC2_INSTANCE_TERMINATE_ERROR"
                ],
                "TopicARN": {"Ref": "OperatorTopic"}
            },
            "LaunchConfigurationName": {"Ref": config_name},
            "VPCZoneIdentifier": {"Fn::FindInMap": ["ServerSubnets"]},
            "AvailabilityZones": {"Fn::GetAZs": ""}
        }
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
    definition = component_auto_scaling_group(definition, configuration, args, info)

    userdata = "#taupage-ami-config\n" + yaml.dump(configuration["TaupageConfig"], default_flow_style=False)

    config_name = configuration["Name"] + "Config"
    ensure_keys(definition, "Resources", config_name, "Properties", "UserData")
    definition["Resources"][config_name]["Properties"]["UserData"]["Fn::Base64"] = userdata

    return definition


def component_load_balancer(definition, configuration, args, info):
    return definition

# TODO make extendable
COMPONENTS = {
    "Senza::Configuration": component_basic_configuration,
    "Senza::AutoScalingGroup": component_auto_scaling_group,
    "Senza::TaupageAutoScalingGroup": component_taupage_auto_scaling_group,
    "Senza::ElasticLoadBalancer": component_load_balancer,
}

BASE_TEMPLATE = {
    "AWSTemplateFormatVersion": "2010-09-09"
}


def evaluate(definition, args):
    # extract Senza* meta information
    info = definition["SenzaInfo"]
    definition.pop("SenzaInfo")

    components = definition["SenzaComponents"]
    definition.pop("SenzaComponents")

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

    return definition


## all actions

def load_yaml(file):
    stream = open(file, 'r')
    return yaml.load(stream)


def action_print(args):
    template = evaluate(load_yaml(args.definition), args)
    print(json.dumps(template, sort_keys=True, indent=4))


def action_create(args):
    pass


def action_show(args):
    print(args)


def action_delete(args):
    pass


## basic argument parsing

def args_none(definition):
    return []


def args_version(definition):
    return [{"region": "In which region to operate."},
            {"version": "The stack version."}]


def args_generation(definition):
    arguments = args_version(definition)

    # get user defined arguments
    document = load_yaml(definition)
    for parameter in document["SenzaInfo"]["Parameters"]:
        name, value = named_value(parameter)
        arguments.append({name: value["Description"]})

    return arguments


ACTIONS = {
    "print": {"fn": action_print,
              "desc": "prints the generated cloud formation template",
              "args": args_generation},
    "create": {"fn": action_create,
               "desc": "creates a new cloud formation stack from the definition",
               "args": args_generation},
    "show": {"fn": action_show,
             "desc": "shows all deployed versions of the definition",
             "args": args_none},
    "delete": {"fn": action_delete,
               "desc": "deletes a cloud formation stack",
               "args": args_version},
}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("definition", help="The senza deployment definition.")
    parser.add_argument("action", help="The action to perform on the definition.")

    offset = 0
    if len(sys.argv) >= 1 and sys.argv[1] == "-h":
        offset = 1

    if len(sys.argv) >= 3 + offset:
        definition = sys.argv[1 + offset]
        actionname = sys.argv[2 + offset]

        action = ACTIONS[actionname]
        arguments = action["args"](definition)
        for argument in arguments:
            name, desc = named_value(argument)
            parser.add_argument(name, help=desc)

    args = parser.parse_args()
    actionfn = ACTIONS[args.action]["fn"]
    actionfn(args)


if __name__ == "__main__":
    main()
