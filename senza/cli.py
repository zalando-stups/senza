#!/usr/bin/env python3
import calendar
import collections
import configparser
import datetime
import functools
import importlib
import os
import re
import sys
import json
import dns.resolver
import time

from boto.exception import BotoServerError
import click
from clickclick import AliasedGroup, Action, choice, info, FloatRange, OutputFormat
from clickclick.console import print_table
import requests
import yaml
import boto.cloudformation
import boto.vpc
import boto.ec2
import boto.ec2.autoscale
import boto.iam
import boto.sns
import boto.route53

from .aws import parse_time, get_required_capabilities, resolve_topic_arn, get_stacks, StackReference, matches_any
from .components import component_basic_configuration, component_stups_auto_configuration, \
    component_auto_scaling_group, component_taupage_auto_scaling_group, \
    component_load_balancer, component_weighted_dns_load_balancer, component_iam_role, evaluate_template
import senza
from .traffic import change_version_traffic, print_version_traffic
from .utils import named_value, camel_case_to_underscore


CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

STYLES = {
    'RUNNING': {'fg': 'green'},
    'TERMINATED': {'fg': 'red'},
    'DELETE_COMPLETE': {'fg': 'red'},
    'ROLLBACK_COMPLETE': {'fg': 'red'},
    'CREATE_COMPLETE': {'fg': 'green'},
    'CREATE_FAILED': {'fg': 'red'},
    'PENDING': {'fg': 'yellow', 'bold': True},
    'CREATE_IN_PROGRESS': {'fg': 'yellow', 'bold': True},
    'DELETE_IN_PROGRESS': {'fg': 'red', 'bold': True},
    'SHUTTING_DOWN': {'fg': 'red', 'bold': True},
    'ROLLBACK_IN_PROGRESS': {'fg': 'red', 'bold': True},
    'IN_SERVICE': {'fg': 'green'},
    'OUT_OF_SERVICE': {'fg': 'red'},
    'OK': {'fg': 'green'},
    'ERROR': {'fg': 'red'},
    }


TITLES = {
    'creation_time': 'Created',
    'logical_resource_id': 'Resource ID',
    'launch_time': 'Launched',
    'resource_status': 'Status',
    'resource_status_reason': 'Status Reason',
    'lb_status': 'LB Status',
    'private_ip': 'Private IP',
    'public_ip': 'Public IP',
    'resource_id': 'Resource ID',
    'instance_id': 'Instance ID',
    'version': 'Ver.',
    'total_instances': 'Inst.#',
    'running_instances': 'Running',
    'healthy_instances': 'Healthy',
    'http_status': 'HTTP',
    'main_dns': 'Main DNS',
    'id': 'ID',
    'owner_id': 'Owner'
}

MAX_COLUMN_WIDTHS = {
    'description': 50,
    'stacks': 20,
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


class KeyValParamType(click.ParamType):
    '''
    >>> KeyValParamType().convert(('a', 'b'), None, None)
    ('a', 'b')
    '''
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


region_option = click.option('--region', envvar='AWS_DEFAULT_REGION', metavar='AWS_REGION_ID',
                             help='AWS region ID (e.g. eu-west-1)')
output_option = click.option('-o', '--output', type=click.Choice(['text', 'json', 'tsv']), default='text',
                             help='Use alternative output format')
watch_option = click.option('-w', '--watch', type=click.IntRange(1, 300), metavar='SECS',
                            help='Auto update the screen every X seconds')


def watching(watch: int):
    if watch:
        click.clear()
    yield 0
    if watch:
        while True:
            time.sleep(watch)
            click.clear()
            yield 0


# from AWS docs:
# Stack name must contain only alphanumeric characters (case sensitive)
# and start with an alpha character. Maximum length of the name is 255 characters.
STACK_NAME_PATTERN = re.compile(r'^[a-zA-Z][a-zA-Z0-9-]*$')
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
    "Senza::IamRole": component_iam_role
}

BASE_TEMPLATE = {
    'AWSTemplateFormatVersion': '2010-09-09'
}


def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo('Senza {}'.format(senza.__version__))
    ctx.exit()


def evaluate(definition, args, force: bool):
    # extract Senza* meta information
    info = definition.pop("SenzaInfo")
    info["StackVersion"] = args.version

    template = yaml.dump(definition, default_flow_style=False)
    definition = evaluate_template(template, info, [], args)
    definition = yaml.load(definition)

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

        definition = componentfn(definition, configuration, args, info, force)

    # throw executed template to templating engine and provide all information for substitutions
    template = yaml.dump(definition, default_flow_style=False)
    definition = evaluate_template(template, info, components, args)
    definition = yaml.load(definition)

    return definition


def handle_exceptions(func):
    @functools.wraps(func)
    def wrapper():
        try:
            func()
        except boto.exception.NoAuthHandlerFound as e:
            sys.stderr.write('No AWS credentials found. ' +
                             'Use the "mai" command line tool to get a temporary access key\n')
            sys.stderr.write('or manually configure either ~/.aws/credentials ' +
                             'or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY.\n')
            sys.exit(1)
        except BotoServerError as e:
            if is_credentials_expired_error(e):
                sys.stderr.write('AWS credentials have expired. ' +
                                 'Use the "mai" command line tool to get a new temporary access key.\n')
                sys.exit(1)
            else:
                raise
    return wrapper


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


def check_credentials(region):
    iam = boto.iam.connect_to_region(region)
    return iam.get_account_alias()


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
        except Exception as e:
            if not STACK_NAME_PATTERN.match(ref):
                # we can be sure that ref is a file path,
                # as stack names cannot contain dots or slashes
                raise click.FileError(ref, str(e))

        if refs:
            version = refs.pop()
        else:
            version = None
        stack_refs.append(StackReference(ref, version))
    return stack_refs


@cli.command('list')
@region_option
@output_option
@watch_option
@click.option('--all', is_flag=True, help='Show all stacks, including deleted ones')
@click.argument('stack_ref', nargs=-1)
def list_stacks(region, stack_ref, all, output, watch):
    '''List Cloud Formation stacks'''
    region = get_region(region)

    stack_refs = get_stack_refs(stack_ref)

    for _ in watching(watch):
        rows = []
        for stack in get_stacks(stack_refs, region, all=all):
            rows.append({'stack_name': stack.name,
                         'version': stack.version,
                         'status': stack.stack_status,
                         'creation_time': calendar.timegm(stack.creation_time.timetuple()),
                         'description': stack.template_description})

        rows.sort(key=lambda x: (x['stack_name'], x['version']))

        with OutputFormat(output):
            print_table('stack_name version status creation_time description'.split(), rows,
                        styles=STYLES, titles=TITLES)


@cli.command()
@click.argument('definition', type=DEFINITION)
@click.argument('version', callback=validate_version)
@click.argument('parameter', nargs=-1)
@region_option
@click.option('--disable-rollback', is_flag=True, help='Disable Cloud Formation rollback on failure')
@click.option('--dry-run', is_flag=True, help='No-op mode: show what would be created')
@click.option('-f', '--force', is_flag=True, help='Ignore failing validation checks')
def create(definition, region, version, parameter, disable_rollback, dry_run, force):
    '''Create a new Cloud Formation stack from the given Senza definition file'''

    input = definition

    region = get_region(region)
    args = parse_args(input, region, version, parameter)

    with Action('Generating Cloud Formation template..'):
        data = evaluate(input.copy(), args, force)
        cfjson = json.dumps(data, sort_keys=True, indent=4)

    stack_name = "{0}-{1}".format(input["SenzaInfo"]["StackName"], version)

    parameters = []
    for name, parameter in data.get("Parameters", {}).items():
        parameters.append([name, getattr(args, name, None)])

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
@region_option
@click.option('-f', '--force', is_flag=True, help='Ignore failing validation checks')
def print_cfjson(definition, region, version, parameter, force):
    '''Print the generated Cloud Formation template'''
    input = definition
    region = get_region(region)
    args = parse_args(input, region, version, parameter)
    data = evaluate(input.copy(), args, force)
    cfjson = json.dumps(data, sort_keys=True, indent=4)

    click.secho(cfjson)


@cli.command()
@click.argument('stack_ref', nargs=-1)
@region_option
@click.option('--dry-run', is_flag=True, help='No-op mode: show what would be deleted')
@click.option('-f', '--force', is_flag=True, help='Allow deleting multiple stacks')
def delete(stack_ref, region, dry_run, force):
    '''Delete a single Cloud Formation stack'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)
    cf = boto.cloudformation.connect_to_region(region)

    if not stack_refs:
        raise click.UsageError('Please specify at least one stack')

    stacks = list(get_stacks(stack_refs, region))

    if len(stacks) > 1 and not dry_run and not force:
        raise click.UsageError(('{} matching stacks found. ' +
                               'Please use the "--force" flag if you really want to delete multiple stacks.').format(
                               len(stacks)))

    for stack in stacks:
        with Action('Deleting Cloud Formation stack {}..'.format(stack.stack_name)):
            if not dry_run:
                cf.delete_stack(stack.stack_name)


def format_resource_type(resource_type):
    if resource_type and resource_type.startswith('AWS::'):
        return resource_type[5:]
    return resource_type


@cli.command()
@click.argument('stack_ref', nargs=-1)
@region_option
@watch_option
@output_option
def resources(stack_ref, region, watch, output):
    '''Show all resources of a single Cloud Formation stack'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)
    cf = boto.cloudformation.connect_to_region(region)

    for _ in watching(watch):
        rows = []
        for stack in get_stacks(stack_refs, region):
            resources = cf.describe_stack_resources(stack.stack_name)

            for resource in resources:
                d = resource.__dict__
                d['stack_name'] = stack.name
                d['version'] = stack.version
                d['resource_type'] = format_resource_type(d['resource_type'])
                d['creation_time'] = calendar.timegm(resource.timestamp.timetuple())
                rows.append(d)

        rows.sort(key=lambda x: (x['stack_name'], x['version'], x['logical_resource_id']))

        with OutputFormat(output):
            print_table('stack_name version logical_resource_id resource_type resource_status creation_time'.split(),
                        rows, styles=STYLES, titles=TITLES)


@cli.command()
@click.argument('stack_ref', nargs=-1)
@region_option
@watch_option
@output_option
def events(stack_ref, region, watch, output):
    '''Show all Cloud Formation events for a single stack'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)
    cf = boto.cloudformation.connect_to_region(region)

    for _ in watching(watch):
        rows = []
        for stack in get_stacks(stack_refs, region):
            events = cf.describe_stack_events(stack.stack_name)

            for event in events:
                d = event.__dict__
                d['stack_name'] = stack.name
                d['version'] = stack.version
                d['resource_type'] = format_resource_type(d['resource_type'])
                d['event_time'] = calendar.timegm(event.timestamp.timetuple())
                rows.append(d)

        rows.sort(key=lambda x: x['event_time'])

        with OutputFormat(output):
            print_table(('stack_name version resource_type logical_resource_id ' +
                        'resource_status resource_status_reason event_time').split(),
                        rows, styles=STYLES, titles=TITLES, max_column_widths=MAX_COLUMN_WIDTHS)


def get_template_description(template: str):
    module = importlib.import_module('senza.templates.{}'.format(template))
    return '{}: {}'.format(template, module.__doc__.strip())


@cli.command()
@click.argument('definition_file', type=click.File('w'))
@region_option
@click.option('-t', '--template', help='Use a custom template', metavar='TEMPLATE_ID')
@click.option('-v', '--user-variable', help='Provide user variables for the template',
              metavar='KEY=VAL', multiple=True, type=KEY_VAL)
def init(definition_file, region, template, user_variable):
    '''Initialize a new Senza definition'''
    region = get_region(region)
    check_credentials(region)

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
        definition_file.write(definition)


def get_instance_health(elb, stack_name: str) -> dict:
    instance_health = {}
    try:
        instance_states = elb.describe_instance_health(stack_name)
        for istate in instance_states:
            instance_health[istate.instance_id] = camel_case_to_underscore(istate.state).upper()
    except boto.exception.BotoServerError as e:
        # ignore non existing ELBs
        # ignore ValidationError "LoadBalancer name cannot be longer than 32 characters"
        if e.code not in ('LoadBalancerNotFound', 'ValidationError'):
            raise
    return instance_health


@cli.command()
@click.argument('stack_ref', nargs=-1)
@region_option
@output_option
@watch_option
def instances(stack_ref, region, output, watch):
    '''List the stack's EC2 instances'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)

    conn = boto.ec2.connect_to_region(region)
    elb = boto.ec2.elb.connect_to_region(region)

    for _ in watching(watch):
        rows = []
        for stack in get_stacks(stack_refs, region):
            if stack.stack_status == 'ROLLBACK_COMPLETE':
                # performance optimization: do not call EC2 API for "dead" stacks
                continue

            instance_health = get_instance_health(elb, stack.stack_name)

            for instance in conn.get_only_instances(filters={'tag:aws:cloudformation:stack-id': stack.stack_id}):
                rows.append({'stack_name': stack.name,
                             'version': stack.version,
                             'resource_id': instance.tags.get('aws:cloudformation:logical-id'),
                             'instance_id': instance.id,
                             'public_ip': instance.ip_address,
                             'private_ip': instance.private_ip_address,
                             'state': instance.state.upper().replace('-', '_'),
                             'lb_status': instance_health.get(instance.id),
                             'launch_time': parse_time(instance.launch_time)})

        with OutputFormat(output):
            print_table(('stack_name version resource_id instance_id public_ip ' +
                         'private_ip state lb_status launch_time').split(), rows, styles=STYLES, titles=TITLES)


@cli.command()
@click.argument('stack_ref', nargs=-1)
@region_option
@output_option
@watch_option
def status(stack_ref, region, output, watch):
    '''Show stack status information'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)

    conn = boto.ec2.connect_to_region(region)
    elb = boto.ec2.elb.connect_to_region(region)
    cf = boto.cloudformation.connect_to_region(region)

    for _ in watching(watch):
        rows = []
        for stack in sorted(get_stacks(stack_refs, region)):
            instance_health = get_instance_health(elb, stack.stack_name)

            main_dns_resolves = False
            http_status = None
            resources = cf.describe_stack_resources(stack.stack_id)
            for res in resources:
                if res.resource_type == 'AWS::Route53::RecordSet':
                    name = res.physical_resource_id
                    if not name:
                        # physical resource ID will be empty during stack creation
                        continue
                    if 'version' in res.logical_resource_id.lower():
                        try:
                            requests.get('https://{}/'.format(name), timeout=2)
                            http_status = 'OK'
                        except:
                            http_status = 'ERROR'
                    else:
                        try:
                            answers = dns.resolver.query(name, 'CNAME')
                        except:
                            answers = []
                        for answer in answers:
                            if answer.target.to_text().startswith('{}-'.format(stack.stack_name)):
                                main_dns_resolves = True

            instances = conn.get_only_instances(filters={'tag:aws:cloudformation:stack-id': stack.stack_id})
            rows.append({'stack_name': stack.name,
                         'version': stack.version,
                         'status': stack.stack_status,
                         'total_instances': len(instances),
                         'running_instances': len([i for i in instances if i.state == 'running']),
                         'healthy_instances': len([i for i in instance_health.values() if i == 'IN_SERVICE']),
                         'lb_status': ','.join(set(instance_health.values())),
                         'main_dns': main_dns_resolves,
                         'http_status': http_status
                         })

        with OutputFormat(output):
            print_table(('stack_name version status total_instances running_instances healthy_instances ' +
                         'lb_status http_status main_dns').split(), rows, styles=STYLES, titles=TITLES)


@cli.command()
@click.argument('stack_ref', nargs=-1)
@region_option
@output_option
@watch_option
def domains(stack_ref, region, output, watch):
    '''List the stack's Route53 domains'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)

    cf = boto.cloudformation.connect_to_region(region)
    route53 = boto.route53.connect_to_region(region)

    records_by_name = {}

    for _ in watching(watch):
        rows = []
        for stack in get_stacks(stack_refs, region):
            if stack.stack_status == 'ROLLBACK_COMPLETE':
                # performance optimization: do not call EC2 API for "dead" stacks
                continue

            resources = cf.describe_stack_resources(stack.stack_id)
            for res in resources:
                if res.resource_type == 'AWS::Route53::RecordSet':
                    name = res.physical_resource_id
                    if name not in records_by_name:
                        zone_name = name.split('.', 1)[1]
                        zone = route53.get_zone(zone_name)
                        for rec in zone.get_records():
                            records_by_name[(rec.name.rstrip('.'), rec.identifier)] = rec
                    record = records_by_name.get((name, stack.stack_name)) or records_by_name.get((name, None))
                    rows.append({'stack_name': stack.name,
                                 'version': stack.version,
                                 'resource_id': res.logical_resource_id,
                                 'domain': res.physical_resource_id,
                                 'weight': record.weight if record else None,
                                 'type': record.type if record else None,
                                 'value': ','.join(record.resource_records) if record else None,
                                 'create_time': calendar.timegm(res.timestamp.timetuple())})

        with OutputFormat(output):
            print_table('stack_name version resource_id domain weight type value create_time'.split(),
                        rows, styles=STYLES, titles=TITLES)


@cli.command()
@click.argument('stack_name')
@click.argument('stack_version', required=False)
@click.argument('percentage', type=FloatRange(0, 100, clamp=True), required=False)
@region_option
@output_option
def traffic(stack_name, stack_version, percentage, region, output):
    '''Route traffic to a specific stack (weighted DNS record)'''
    stack_refs = get_stack_refs([stack_name, stack_version])
    region = get_region(region)

    with OutputFormat(output):
        for ref in stack_refs:
            if percentage is None:
                print_version_traffic(ref, region)
            else:
                change_version_traffic(ref, percentage, region)


@cli.command()
@click.argument('stack_ref', nargs=-1)
@click.option('--hide-older-than', help='Hide images older than X days (default: 21)',
              type=int, default=21, metavar='DAYS')
@click.option('--show-instances', is_flag=True, help='Show EC2 instance IDs')
@region_option
@output_option
def images(stack_ref, region, output, hide_older_than, show_instances):
    '''Show all used AMIs and available Taupage AMIs'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)

    conn = boto.ec2.connect_to_region(region)

    instances_by_image = collections.defaultdict(list)
    for inst in conn.get_only_instances():
        if inst.state == 'terminated':
            # do not count TERMINATED EC2 instances
            continue
        stack_name = inst.tags.get('aws:cloudformation:stack-name')
        if not stack_refs or matches_any(stack_name, stack_refs):
            instances_by_image[inst.image_id].append(inst)

    images = {}
    for image in conn.get_all_images(filters={'image-id': list(instances_by_image.keys())}):
        images[image.id] = image
    if not stack_refs:
        filters = {'name': '*Taupage-*',
                   'state': 'available'}
        for image in conn.get_all_images(filters=filters):
            images[image.id] = image
    rows = []
    cutoff = datetime.datetime.now() - datetime.timedelta(days=hide_older_than)
    for image in images.values():
        row = image.__dict__
        # TODO: fix UTC/local time offset
        creation_time = datetime.datetime.strptime(image.creationDate, '%Y-%m-%dT%H:%M:%S.%fZ')
        row['creation_time'] = creation_time.timestamp()
        row['instances'] = ', '.join(sorted(i.id for i in instances_by_image[image.id]))
        row['total_instances'] = len(instances_by_image[image.id])
        stacks = set()
        for instance in instances_by_image[image.id]:
            stack_name = instance.tags.get('aws:cloudformation:stack-name')
            # EC2 instance might not be part of a CF stack
            if stack_name:
                stacks.add(stack_name)
        row['stacks'] = ', '.join(sorted(stacks))

        #
        if creation_time > cutoff or row['total_instances']:
            rows.append(row)

    rows.sort(key=lambda x: x.get('name'))
    with OutputFormat(output):
        cols = 'id name owner_id description stacks total_instances creation_time'
        if show_instances:
            cols = cols.replace('total_instances', 'instances')
        print_table(cols.split(), rows, titles=TITLES, max_column_widths=MAX_COLUMN_WIDTHS)


def main():
    handle_exceptions(cli)()


if __name__ == "__main__":
    main()
