#!/usr/bin/env python3
import calendar
import configparser
import importlib
import os
import re
import sys
import json
import time

from boto.exception import BotoServerError
import click
from clickclick import AliasedGroup, Action, choice, info
from clickclick.console import print_table
import collections
import yaml
import pystache
import boto.cloudformation
import boto.vpc
import boto.ec2
import boto.ec2.autoscale
import boto.iam
import boto.sns
import boto.route53
from .aws import parse_time, get_required_capabilities, resolve_topic_arn

from .components import component_basic_configuration, component_stups_auto_configuration, \
    component_auto_scaling_group, component_taupage_auto_scaling_group, \
    component_load_balancer, component_weighted_dns_load_balancer
import senza
from .utils import named_value, camel_case_to_underscore


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

STYLES = {
    'RUNNING': {'fg': 'green'},
    'TERMINATED': {'fg': 'red'},
    'DELETE_COMPLETE': {'fg': 'red'},
    'ROLLBACK_COMPLETE': {'fg': 'red'},
    'CREATE_COMPLETE': {'fg': 'green'},
    'CREATE_FAILED': {'fg': 'red'},
    'CREATE_IN_PROGRESS': {'fg': 'yellow', 'bold': True},
    'DELETE_IN_PROGRESS': {'fg': 'red', 'bold': True},
    'ROLLBACK_IN_PROGRESS': {'fg': 'red', 'bold': True},
    'IN_SERVICE': {'fg': 'green'},
    'OUT_OF_SERVICE': {'fg': 'red'},
    }


TITLES = {
    'creation_time': 'Created',
    'logical_resource_id': 'ID',
    'launch_time': 'Launched',
    'resource_status': 'Status',
    'resource_status_reason': 'Status Reason',
    'lb_status': 'LB Status',
    'private_ip': 'Private IP',
    'public_ip': 'Public IP',
    'resource_id': 'Resource ID',
    'instance_id': 'Instance ID',
}

MAX_COLUMN_WIDTHS = {
    'resource_status_reason': 50
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


class StackReference(collections.namedtuple('StackReference', 'name version')):
    def cf_stack_name(self):
        return '{}-{}'.format(self.name, self.version)


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


VERSION_PATTERN = re.compile(r'^[a-zA-Z0-9]+$')


def validate_version(ctx, param, value):
    if not VERSION_PATTERN.match(value):
        raise click.BadParameter('Version must satisfy regular expression pattern "[a-zA-Z0-9]+"')
    return value


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


def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo('Senza {}'.format(senza.__version__))
    ctx.exit()


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
@click.option('-V', '--version', is_flag=True, callback=print_version, expose_value=False, is_eager=True,
              help='Print the current version number and exit.')
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


def get_stack_refs(refs: list):
    '''
    >>> get_stack_refs(['foobar-stack'])
    [StackReference(name='foobar-stack', version=None)]

    >>> get_stack_refs(['foobar-stack', '1'])
    [StackReference(name='foobar-stack', version='1')]

    >>> get_stack_refs(['foobar-stack', '1', 'other-stack'])
    [StackReference(name='foobar-stack', version='1'), StackReference(name='other-stack', version=None)]
    '''
    refs = list(refs)
    refs.reverse()
    stack_refs = []
    while refs:
        ref = refs.pop()
        try:
            with open(ref) as fd:
                data = yaml.safe_load(fd)
            ref = data['SenzaInfo']['StackName']
        except:
            pass

        if refs:
            version = refs.pop()
        else:
            version = None
        stack_refs.append(StackReference(ref, version))
    return stack_refs


def matches_any(cf_stack_name: str, stack_refs: list):
    '''
    >>> matches_any('foobar-1', [])
    False

    >>> matches_any('foobar-1', [StackReference(name='foobar', version=None)])
    True

    >>> matches_any('foobar-1', [StackReference(name='foobar', version='1')])
    True

    >>> matches_any('foobar-1', [StackReference(name='foobar', version='2')])
    False
    '''
    for ref in stack_refs:
        if ref.version and cf_stack_name == ref.cf_stack_name():
            return True
        elif not ref.version and cf_stack_name.rsplit('-', 1)[0] == ref.name:
            return True
    return False


def get_stacks(stack_refs: list, region, all=False):
    cf = boto.cloudformation.connect_to_region(region)
    if all:
        status_filter = None
    else:
        status_filter = [st for st in cf.valid_states if st != 'DELETE_COMPLETE']
    stacks = cf.list_stacks(stack_status_filters=status_filter)
    for stack in stacks:
        if not stack_refs or matches_any(stack.stack_name, stack_refs):
            yield stack


@cli.command('list')
@click.option('--region', envvar='AWS_DEFAULT_REGION', metavar='AWS_REGION_ID', help='AWS region ID (e.g. eu-west-1)')
@click.option('--all', is_flag=True, help='Show all stacks, including deleted ones')
@click.argument('stack_ref', nargs=-1)
def list_stacks(region, stack_ref, all):
    '''List Cloud Formation stacks'''
    region = get_region(region)

    stack_refs = get_stack_refs(stack_ref)

    rows = []
    for stack in get_stacks(stack_refs, region, all=all):
        rows.append({'Name': stack.stack_name, 'Status': stack.stack_status,
                     'creation_time': calendar.timegm(stack.creation_time.timetuple()),
                     'Description': stack.template_description})

    rows.sort(key=lambda x: x['Name'])

    print_table('Name Status creation_time Description'.split(), rows, styles=STYLES, titles=TITLES)


@cli.command()
@click.argument('definition', type=DEFINITION)
@click.argument('version', callback=validate_version)
@click.argument('parameter', nargs=-1)
@click.option('--region', envvar='AWS_DEFAULT_REGION', metavar='AWS_REGION_ID', help='AWS region ID (e.g. eu-west-1)')
@click.option('--disable-rollback', is_flag=True, help='Disable Cloud Formation rollback on failure')
@click.option('--dry-run', is_flag=True, help='No-op mode: show what would be created')
def create(definition, region, version, parameter, disable_rollback, dry_run):
    '''Create a new Cloud Formation stack from the given Senza definition file'''

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
        topic = input["SenzaInfo"]["OperatorTopicId"]
        topic_arn = resolve_topic_arn(region, topic)
        if not topic_arn:
            raise click.UsageError('SNS topic "{}" does not exist'.format(topic))
        topics = [topic_arn]
    else:
        topics = None

    capabilities = get_required_capabilities(data)

    cf = boto.cloudformation.connect_to_region(region)

    with Action('Creating Cloud Formation stack {}..'.format(stack_name)):
        try:
            if dry_run:
                info('**DRY-RUN** {}'.format(topics))
            else:
                cf.create_stack(stack_name, template_body=cfjson, parameters=parameters, tags=tags,
                                notification_arns=topics, disable_rollback=disable_rollback, capabilities=capabilities)
        except boto.exception.BotoServerError as e:
            if e.error_code == 'AlreadyExistsException':
                raise click.UsageError('Stack {} already exists. Please choose another version.'.format(stack_name))
            else:
                raise


@cli.command('print')
@click.argument('definition', type=DEFINITION)
@click.argument('version', callback=validate_version)
@click.argument('parameter', nargs=-1)
@click.option('--region', envvar='AWS_DEFAULT_REGION', metavar='AWS_REGION_ID', help='AWS region ID (e.g. eu-west-1)')
def print_cfjson(definition, region, version, parameter):
    '''Print the generated Cloud Formation template'''
    input = definition
    region = get_region(region)
    args = parse_args(input, region, version, parameter)
    data = evaluate(input.copy(), args)
    cfjson = json.dumps(data, sort_keys=True, indent=4)

    click.secho(cfjson)


@cli.command()
@click.argument('stack_ref', nargs=-1)
@click.option('--region', envvar='AWS_DEFAULT_REGION', metavar='AWS_REGION_ID', help='AWS region ID (e.g. eu-west-1)')
@click.option('--dry-run', is_flag=True, help='No-op mode: show what would be deleted')
def delete(stack_ref, region, dry_run):
    '''Delete a single Cloud Formation stack'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)
    cf = boto.cloudformation.connect_to_region(region)

    if not stack_refs:
        raise click.UsageError('Please specify at least one stack')

    for stack in get_stacks(stack_refs, region):
        with Action('Deleting Cloud Formation stack {}..'.format(stack.stack_name)):
            if not dry_run:
                cf.delete_stack(stack.stack_name)


def format_resource_type(resource_type):
    if resource_type and resource_type.startswith('AWS::'):
        return resource_type[5:]
    return resource_type


@cli.command()
@click.argument('stack_ref', nargs=-1)
@click.option('--region', envvar='AWS_DEFAULT_REGION', metavar='AWS_REGION_ID', help='AWS region ID (e.g. eu-west-1)')
@click.option('-w', '--watch', type=click.IntRange(1, 300), help='Auto update the screen every X seconds',
              metavar='SECS')
def resources(stack_ref, region, watch):
    '''Show all resources of a single Cloud Formation stack'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)
    cf = boto.cloudformation.connect_to_region(region)

    repeat = True

    while repeat:
        for stack in get_stacks(stack_refs, region):
            resources = cf.describe_stack_resources(stack.stack_name)

            rows = []
            for resource in resources:
                d = resource.__dict__
                d['resource_type'] = format_resource_type(d['resource_type'])
                d['creation_time'] = calendar.timegm(resource.timestamp.timetuple())
                rows.append(d)

            print_table('logical_resource_id resource_type resource_status creation_time'.split(), rows,
                        styles=STYLES, titles=TITLES)
        if watch:
            time.sleep(watch)
            click.clear()
        else:
            repeat = False


@cli.command()
@click.argument('stack_ref', nargs=-1)
@click.option('--region', envvar='AWS_DEFAULT_REGION', metavar='AWS_REGION_ID', help='AWS region ID (e.g. eu-west-1)')
@click.option('-w', '--watch', type=click.IntRange(1, 300), help='Auto update the screen every X seconds',
              metavar='SECS')
def events(stack_ref, region, watch):
    '''Show all Cloud Formation events for a single stack'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)
    cf = boto.cloudformation.connect_to_region(region)

    repeat = True

    while repeat:
        for stack in get_stacks(stack_refs, region):
            events = cf.describe_stack_events(stack.stack_name)

            rows = []
            for event in sorted(events, key=lambda x: x.timestamp):
                d = event.__dict__
                d['resource_type'] = format_resource_type(d['resource_type'])
                d['event_time'] = calendar.timegm(event.timestamp.timetuple())
                rows.append(d)

            print_table('resource_type logical_resource_id resource_status resource_status_reason event_time'.split(),
                        rows, styles=STYLES, titles=TITLES, max_column_widths=MAX_COLUMN_WIDTHS)
        if watch:
            time.sleep(watch)
            click.clear()
        else:
            repeat = False


def get_template_description(template: str):
    module = importlib.import_module('senza.templates.{}'.format(template))
    return '{}: {}'.format(template, module.__doc__.strip())


@cli.command()
@click.argument('definition_file', type=click.File('w'))
@click.option('--region', envvar='AWS_DEFAULT_REGION', metavar='AWS_REGION_ID', help='AWS region ID (e.g. eu-west-1)')
@click.option('-t', '--template', help='Use a custom template', metavar='TEMPLATE_ID')
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


@cli.command()
@click.argument('stack_ref', nargs=-1)
@click.option('--region', envvar='AWS_DEFAULT_REGION', metavar='AWS_REGION_ID', help='AWS region ID (e.g. eu-west-1)')
def instances(stack_ref, region):
    '''List the stack's EC2 instances'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)

    conn = boto.ec2.connect_to_region(region)
    elb = boto.ec2.elb.connect_to_region(region)

    rows = []
    for stack in get_stacks(stack_refs, region):
        if stack.stack_status == 'ROLLBACK_COMPLETE':
            # performance optimization: do not call EC2 API for "dead" stacks
            continue

        instance_health = {}
        try:
            instance_states = elb.describe_instance_health(stack.stack_name)
            for istate in instance_states:
                instance_health[istate.instance_id] = camel_case_to_underscore(istate.state).upper()
        except boto.exception.BotoServerError as e:
            if e.code != 'LoadBalancerNotFound':
                raise

        for instance in conn.get_only_instances(filters={'tag:aws:cloudformation:stack-id': stack.stack_id}):
            rows.append({'stack_name': stack.stack_name,
                         'resource_id': instance.tags.get('aws:cloudformation:logical-id'),
                         'instance_id': instance.id,
                         'public_ip': instance.ip_address,
                         'private_ip': instance.private_ip_address,
                         'state': instance.state.upper(),
                         'lb_status': instance_health.get(instance.id),
                         'launch_time': parse_time(instance.launch_time)})

    print_table('stack_name resource_id instance_id public_ip private_ip state lb_status launch_time'.split(),
                rows, styles=STYLES, titles=TITLES)


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
