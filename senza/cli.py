#!/usr/bin/env python3
import calendar
import configparser
import importlib
import os
import sys
import json
import time

from boto.exception import BotoServerError
import click
from clickclick import AliasedGroup, Action, choice
from clickclick.console import print_table
import yaml
import pystache
import boto.cloudformation
import boto.vpc
import boto.ec2
import boto.iam
import boto.route53

from .components import component_basic_configuration, component_stups_auto_configuration, \
    component_auto_scaling_group, component_taupage_auto_scaling_group, \
    component_load_balancer, component_weighted_dns_load_balancer
from .utils import named_value


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

STYLES = {
    'DELETE_COMPLETE': {'fg': 'red'},
    'ROLLBACK_COMPLETE': {'fg': 'red'},
    'CREATE_COMPLETE': {'fg': 'green'},
    'CREATE_FAILED': {'fg': 'red'},
    'CREATE_IN_PROGRESS': {'fg': 'yellow', 'bold': True},
    'DELETE_IN_PROGRESS': {'fg': 'red', 'bold': True},
    }


TITLES = {
    'creation_time': 'Created',
    'logical_resource_id': 'ID'
}


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
        for key in ['SenzaInfo']:
            if 'SenzaInfo' not in data:
                self.fail('"{}" entry is missing in YAML file "{}"'.format(key, value), param, ctx)
        return data


class KeyValParamType(click.ParamType):
    name = 'key_val'

    def convert(self, value, param, ctx):
        if isinstance(value, str):
            try:
                key, val = value.split('=', 1)
            except:
                self.fail('invalid key value parameter "{}" (must be KEY=VAL)'.format(value))
            key_val = (key, val)
        else:
            key_val = value
        return key_val


DEFINITION = DefinitionParamType()

KEY_VAL = KeyValParamType()

COMPONENTS = {
    "Senza::Configuration": component_basic_configuration,
    "Senza::StupsAutoConfiguration": component_stups_auto_configuration,
    "Senza::AutoScalingGroup": component_auto_scaling_group,
    "Senza::TaupageAutoScalingGroup": component_taupage_auto_scaling_group,
    "Senza::ElasticLoadBalancer": component_load_balancer,
    "Senza::WeightedDnsElasticLoadBalancer": component_weighted_dns_load_balancer,
}

BASE_TEMPLATE = {
    'AWSTemplateFormatVersion': '2010-09-09'
}


def evaluate(definition, args):
    # extract Senza* meta information
    info = definition.pop("SenzaInfo")
    info["StackVersion"] = args.version

    components = definition.pop("SenzaComponents", [])

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
        try:
            config.read(os.path.expanduser('~/.aws/config'))
            if 'default' in config:
                region = config['default']['region']
        except:
            pass

    if not region:
        raise click.UsageError('Please specify the AWS region on the command line (--region) or in ~/.aws/config')

    cf = boto.cloudformation.connect_to_region(region)
    if not cf:
        raise click.UsageError('Invalid region "{}"'.format(region))
    return region


@cli.command('list')
@click.option('--region', envvar='AWS_DEFAULT_REGION')
@click.option('--all', is_flag=True, help='Show all stacks, including deleted ones')
@click.argument('definition', nargs=-1, type=DEFINITION)
def list_stacks(region, definition, all):
    '''List Cloud Formation stacks'''
    region = get_region(region)

    stack_names = set()
    for defn in definition:
        stack_names.add(defn['SenzaInfo']['StackName'])

    cf = boto.cloudformation.connect_to_region(region)
    if all:
        status_filter = None
    else:
        status_filter = [st for st in cf.valid_states if st != 'DELETE_COMPLETE']
    stacks = cf.list_stacks(stack_status_filters=status_filter)
    rows = []
    for stack in stacks:
        if not stack_names or stack.stack_name.rsplit('-', 1)[0] in stack_names:
            rows.append({'Name': stack.stack_name, 'Status': stack.stack_status,
                         'creation_time': calendar.timegm(stack.creation_time.timetuple()),
                         'Description': stack.template_description})

    rows.sort(key=lambda x: x['Name'])

    print_table('Name Status creation_time Description'.split(), rows, styles=STYLES, titles=TITLES)


@cli.command()
@click.argument('definition', type=DEFINITION)
@click.argument('version')
@click.argument('parameter', nargs=-1)
@click.option('--region', envvar='AWS_DEFAULT_REGION')
@click.option('--disable-rollback', is_flag=True, help='Disable Cloud Formation rollback on failure')
def create(definition, region, version, parameter, disable_rollback):
    '''Create a new stack'''

    input = definition

    region = get_region(region)
    args = parse_args(input, region, version, parameter)

    with Action('Generating Cloud Formation template..'):
        data = evaluate(input.copy(), args)
        cfjson = json.dumps(data, sort_keys=True, indent=4)

    stack_name = "{0}-{1}".format(input["SenzaInfo"]["StackName"], version)

    parameters = []
    for name, parameter in data.get("Parameters", {}).items():
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

    with Action('Creating Cloud Formation stack {}..'.format(stack_name)):
        cf.create_stack(stack_name, template_body=cfjson, parameters=parameters, tags=tags, notification_arns=topics,
                        disable_rollback=disable_rollback)


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
@click.argument('definition', type=DEFINITION)
@click.argument('version')
@click.option('--region', envvar='AWS_DEFAULT_REGION')
def delete(definition, version, region):
    '''Delete a single Cloud Formation stack'''
    region = get_region(region)
    cf = boto.cloudformation.connect_to_region(region)

    stack_name = '{}-{}'.format(definition['SenzaInfo']['StackName'], version)

    with Action('Deleting Cloud Formation stack {}..'.format(stack_name)):
        cf.delete_stack(stack_name)


@cli.command()
@click.argument('definition', type=DEFINITION)
@click.argument('version')
@click.option('--region', envvar='AWS_DEFAULT_REGION')
@click.option('-w', '--watch', type=click.IntRange(1, 300), help='Auto update the screen every X seconds',
              metavar='SECS')
def resources(definition, version, region, watch):
    '''Show all resources of a single Cloud Formation stack'''
    region = get_region(region)
    cf = boto.cloudformation.connect_to_region(region)

    stack_name = '{}-{}'.format(definition['SenzaInfo']['StackName'], version)

    while version:
        resources = cf.describe_stack_resources(stack_name)

        rows = []
        for resource in resources:
            d = resource.__dict__
            d['creation_time'] = calendar.timegm(resource.timestamp.timetuple())
            rows.append(d)

        print_table('logical_resource_id resource_type resource_status creation_time'.split(), rows,
                    styles=STYLES, titles=TITLES)
        if watch:
            time.sleep(watch)
            click.clear()
        else:
            version = False


@cli.command()
@click.argument('definition', type=DEFINITION)
@click.argument('version')
@click.option('--region', envvar='AWS_DEFAULT_REGION')
@click.option('-w', '--watch', type=click.IntRange(1, 300), help='Auto update the screen every X seconds',
              metavar='SECS')
def events(definition, version, region, watch):
    '''Show all Cloud Formation events for a single stack'''
    region = get_region(region)
    cf = boto.cloudformation.connect_to_region(region)

    stack_name = '{}-{}'.format(definition['SenzaInfo']['StackName'], version)

    while version:
        events = cf.describe_stack_events(stack_name)

        rows = []
        for event in sorted(events, key=lambda x: x.timestamp):
            d = event.__dict__
            d['event_time'] = calendar.timegm(event.timestamp.timetuple())
            rows.append(d)

        print_table('resource_type logical_resource_id resource_status event_time'.split(), rows,
                    styles=STYLES, titles=TITLES)
        if watch:
            time.sleep(watch)
            click.clear()
        else:
            version = False


def get_template_description(template: str):
    module = importlib.import_module('senza.templates.{}'.format(template))
    return '{}: {}'.format(template, module.__doc__.strip())


@cli.command()
@click.argument('definition_file', type=click.File('w'))
@click.option('--region', envvar='AWS_DEFAULT_REGION')
@click.option('-t', '--template', help='Use a custom template')
@click.option('-v', '--user-variable', help='Provide user variables for the template',
              metavar='KEY=VAL', multiple=True, type=KEY_VAL)
def init(definition_file, region, template, user_variable):
    '''Initialize a new Senza definition'''
    region = get_region(region)

    templates = []
    for mod in os.listdir(os.path.join(os.path.dirname(__file__), 'templates')):
        if not mod.startswith('_'):
            templates.append(mod.split('.')[0])
    while template not in templates:
        template = choice('Please select the project template',
                          [(t, get_template_description(t)) for t in sorted(templates)])

    module = importlib.import_module('senza.templates.{}'.format(template))
    variables = {}
    for key_val in user_variable:
        key, val = key_val
        variables[key] = val
    variables = module.gather_user_variables(variables, region)
    with Action('Generating Senza definition file {}..'.format(definition_file.name)):
        definition = module.generate_definition(variables)
        yaml.safe_dump(definition, definition_file, default_flow_style=False)


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
