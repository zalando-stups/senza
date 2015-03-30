#!/usr/bin/env python3

import sys
import argparse
import json

import yaml

## all components

def component_basic_configuration(configuration, definition, args):
    if not "Mappings" in definition:
        definition["Mappings"] = {}

    # OperatorEMail
    if "OperatorEMail" in configuration:
        definition["Mappings"]["OperatorEMail"] = configuration["OperatorEMail"]

        if not "Resources" in definition:
            definition["Resources"] = {}

        definition["Resources"]["OperatorTopic"] = {
            "Type": "AWS::SNS::Topic",
            "Properties": {
                "Subscription": [{
                    "Endpoint": {"Ref": "OperatorEMail"},
                    "Protocol": "email"
                }]
            }
        }

    # ServerSubnets
    if not "ServerSubnets" in definition["Mappings"]:
        definition["Mappings"]["ServerSubnets"] = {}

    for region, subnets in configuration["ServerSubnets"].items():
        definition["Mappings"]["ServerSubnets"][region] = subnets

    # LoadBalancerSubnets
    if not "LoadBalancerSubnets" in definition["Mappings"]:
        definition["Mappings"]["LoadBalancerSubnets"] = {}

    for region, subnets in configuration["LoadBalancerSubnets"].items():
        definition["Mappings"]["LoadBalancerSubnets"][region] = subnets


    return definition

def component_taupage_auto_scaling_group(configuration, definition, args):
    return definition

def component_load_balancer(configuration, definition, args):
    return definition

# TODO make extendable
COMPONENTS = {
    "BasicConfiguration": component_basic_configuration,
    "TaupageAutoScalingGroup": component_taupage_auto_scaling_group,
    "LoadBalancer": component_load_balancer,
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
        componentname, configuration = component.popitem()
        componentfn = COMPONENTS[componentname]

        definition = componentfn(configuration, definition, args)

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
    parameters = args_version(definition)

    # get user defined parameters
    document = load_yaml(definition)
    parameters.extend(document["SenzaInfo"]["Parameters"])

    return parameters


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
        parameters = action["args"](definition)
        for parameter in parameters:
            name, desc = parameter.popitem()
            parser.add_argument(name, help=desc)

    args = parser.parse_args()
    actionfn = ACTIONS[args.action]["fn"]
    actionfn(args)


if __name__ == "__main__":
    main()
