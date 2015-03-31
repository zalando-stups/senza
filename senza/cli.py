#!/usr/bin/env python3

import sys
import argparse
import json

import yaml
import pystache
import boto.cloudformation



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
    definition = component_auto_scaling_group(definition, configuration, args, info)

    userdata = "#zalando-ami-config\n" + yaml.dump(configuration["TaupageConfig"], default_flow_style=False)

    config_name = configuration["Name"] + "Config"
    ensure_keys(definition, "Resources", config_name, "Properties", "UserData")
    definition["Resources"][config_name]["Properties"]["UserData"]["Fn::Base64"] = userdata

    return definition


def component_load_balancer(definition, configuration, args, info):
    lb_name = configuration["Name"]

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
                    "SSLCertificateId": configuration["SSLCertificateId"],
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

    # domains pointing to the load balancer
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

    return definition


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


## all actions

def load_yaml(file):
    stream = open(file, 'r')
    return yaml.load(stream)


def action_print(args):
    input = load_yaml(args.definition)
    data = evaluate(input.copy(), args)
    cfjson = json.dumps(data, sort_keys=True, indent=4)

    print(cfjson)


def action_create(args):
    input = load_yaml(args.definition)
    data = evaluate(input.copy(), args)
    cfjson = json.dumps(data, sort_keys=True, indent=4)

    stack_name = "{0}-{1}".format(input["SenzaInfo"]["StackName"], args.version)

    parameters = []
    for name, parameter in data["Parameters"].items():
        parameters.append([name, getattr(args, name)])

    tags = {
        "Name": stack_name,
        "StackName": input["SenzaInfo"]["StackName"],
        "StackVersion": args.version
    }

    if "OperatorTopicId" in input["SenzaInfo"]:
        topics = [input["SenzaInfo"]["OperatorTopicId"]]
    else:
        topics = None

    cf = boto.cloudformation.connect_to_region(args.region)
    cf.create_stack(stack_name, template_body=cfjson, parameters=parameters, tags=tags, notification_arns=topics)


def action_show(args):
    print("not yet implemented")


def action_set_weights(args):
    print("not yet implemented")


def action_delete(args):
    print("not yet implemented")


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
    "set-weights": {"fn": action_set_weights,
                    "desc": "sets the weights for DNS entries",
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
