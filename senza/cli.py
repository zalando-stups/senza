#!/usr/bin/env python3
import calendar
import collections
import configparser
import datetime
import functools
import importlib
import ipaddress
import os
import re
import sys
import json
from urllib.error import URLError
import dns.resolver
import time

from boto.exception import BotoServerError
import click
from clickclick import AliasedGroup, Action, choice, info, FloatRange, OutputFormat, fatal_error
from clickclick.console import print_table
import requests
import yaml
import base64
import boto.cloudformation
import boto.vpc
import boto.ec2
import boto.ec2.autoscale
import boto.iam
import boto.sns
import boto.route53
import boto3

from .aws import parse_time, get_required_capabilities, resolve_topic_arn, get_stacks, StackReference, matches_any, \
    get_account_id, get_account_alias
from .components import get_component, evaluate_template
import senza
from urllib.request import urlopen
from urllib.parse import quote
from .traffic import change_version_traffic, print_version_traffic
from .utils import named_value, camel_case_to_underscore, pystache_render


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
    'docker_source': 'Docker Image Source',
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


def print_json(data, output=None):
    if output == 'yaml':
        parsed_data = yaml.safe_load(data)
        print(yaml.safe_dump(parsed_data, indent=4, default_flow_style=False))
    else:
        print(data)


class DefinitionParamType(click.ParamType):
    name = 'definition'

    def convert(self, value, param, ctx):
        if isinstance(value, str):
            try:
                url = value if '://' in value else 'file://{}'.format(quote(os.path.abspath(value)))
                # if '://' not in value:
                #     url = 'file://{}'.format(quote(os.path.abspath(value)))

                response = urlopen(url)
                data = yaml.safe_load(response.read())
            except URLError:
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
json_output_option = click.option('-o', '--output', type=click.Choice(['json', 'yaml']), default='json',
                                  help='Use alternative output format')
watch_option = click.option('-W', is_flag=True, help='Auto update the screen every 2 seconds')
watchrefresh_option = click.option('-w', '--watch', type=click.IntRange(1, 300), metavar='SECS',
                                   help='Auto update the screen every X seconds')


def watching(w: bool, watch: int):
    if w and not watch:
        watch = 2
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

BASE_TEMPLATE = {
    'AWSTemplateFormatVersion': '2010-09-09'
}


def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return
    click.echo('Senza {}'.format(senza.__version__))
    ctx.exit()


def evaluate(definition, args, account_info, force: bool):
    # extract Senza* meta information
    info = definition.pop("SenzaInfo")
    info["StackVersion"] = args.version

    template = yaml.dump(definition, default_flow_style=False)
    definition = evaluate_template(template, info, [], args, account_info)
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
        componentfn = get_component(componenttype)

        if not componentfn:
            raise click.UsageError('Component "{}" does not exist'.format(componenttype))

        definition = componentfn(definition, configuration, args, info, force)

    # throw executed template to templating engine and provide all information for substitutions
    template = yaml.dump(definition, default_flow_style=False)
    definition = evaluate_template(template, info, components, args, account_info)
    definition = yaml.load(definition)

    return definition


def handle_exceptions(func):
    @functools.wraps(func)
    def wrapper():
        try:
            func()
        except boto.exception.NoAuthHandlerFound as e:
            sys.stdout.flush()
            sys.stderr.write('No AWS credentials found. ' +
                             'Use the "mai" command line tool to get a temporary access key\n')
            sys.stderr.write('or manually configure either ~/.aws/credentials ' +
                             'or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY.\n')
            sys.exit(1)
        except BotoServerError as e:
            if is_credentials_expired_error(e):
                sys.stdout.flush()
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


class AccountArguments:
    '''
    >>> test = AccountArguments('blubber',
    ... AccountID='123456',
    ... AccountAlias='testdummy',
    ... Domain='test.example.org.',
    ... TeamID='superteam')
    >>> test.AccountID
    '123456'
    >>> test.AccountAlias
    'testdummy'
    >>> test.TeamID
    'superteam'
    >>> test.Domain
    'test.example.org.'
    >>> test.blubber
    Traceback (most recent call last):
      File "<stdin>", line 1, in <module>
    AttributeError: 'AccountArguments' object has no attribute 'blubber'
    '''
    def __init__(self, region, **kwargs):
        setattr(self, '__Region', region)
        for key, val in kwargs.items():
            setattr(self, '__' + key, val)

    @property
    def AccountID(self):
        attr = getattr(self, '__AccountID', None)
        if attr is None:
            accountid = get_account_id()
            setattr(self, '__AccountID', accountid)
            return accountid
        return attr

    @property
    def AccountAlias(self):
        attr = getattr(self, '__AccountAlias', None)
        if attr is None:
            accountalias = get_account_alias()
            setattr(self, '__AccountAlias', accountalias)
            return accountalias
        return attr

    @property
    def Region(self):
        return getattr(self, '__Region', None)

    @property
    def Domain(self):
        attr = getattr(self, '__Domain', None)
        if attr is None:
            conn = boto3.client('route53')
            domainlist = conn.list_hosted_zones()['HostedZones']
            if len(domainlist) == 0:
                raise AttributeError('No Domain configured')
            elif len(domainlist) > 1:
                domain = choice('Please select the domain',
                                sorted(domain['Name'] for domain in domainlist))
            else:
                domain = domainlist[0]['Name']
            domain = conn.list_hosted_zones()['HostedZones'][0]['Name']
            setattr(self, '__Domain', domain)
            return domain
        return attr

    @property
    def TeamID(self):
        attr = getattr(self, '__TeamID', None)
        if attr is None:
            team_id = get_account_alias().split('-', maxsplit=1)[-1]
            setattr(self, '__TeamID', team_id)
            return team_id
        return attr


def is_credentials_expired_error(e: BotoServerError) -> bool:
    return (e.status == 400 and 'request has expired' in e.message.lower()) or \
           (e.status == 403 and 'security token included in the request is expired' in e.message.lower())


def parse_args(input, region, version, parameter, account_info):
    paras = {}
    defaults = {}

    # process positional parameters first
    seen_keyword = False
    for i, param in enumerate(input['SenzaInfo'].get('Parameters', [])):
        for key, config in param.items():
            # collect all allowed keys and default values regardless
            paras[key] = None
            defaults[key] = config.get('Default', None)
            if defaults[key] is not None:
                defaults[key] = pystache_render(str(defaults[key]), {'AccountInfo': account_info})
            if i < len(parameter):
                if '=' in parameter[i]:
                    seen_keyword = True
                else:
                    if seen_keyword:
                        raise click.UsageError("Positional parameters must not follow keywords.")
                    paras[key] = parameter[i]

    if len(paras) < len(parameter):
        raise click.UsageError('Too many parameters given.')

    # process keyword parameters separately, if any
    if seen_keyword:
        for i in range(len(parameter)):
            param = parameter[i]
            if '=' in param:
                key, value = param.split('=', 1)  # split only on first =
                if key not in paras:
                    raise click.UsageError('Unrecognized keyword parameter: "{}"'.format(key))
                if paras[key] is not None:
                    raise click.UsageError('Parameter specified multiple times: "{}"'.format(key))
                paras[key] = value

    # finally, make sure every parameter got a value assigned, using defaults if given
    for key, defval in defaults.items():
        paras[key] = paras[key] or defval
        if paras[key] is None:
            raise click.UsageError('Missing parameter "{}"'.format(key))

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
@watchrefresh_option
@click.option('--all', is_flag=True, help='Show all stacks, including deleted ones')
@click.argument('stack_ref', nargs=-1)
def list_stacks(region, stack_ref, all, output, w, watch):
    '''List Cloud Formation stacks'''
    region = get_region(region)
    check_credentials(region)

    stack_refs = get_stack_refs(stack_ref)

    for _ in watching(w, watch):
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
    check_credentials(region)
    account_info = AccountArguments(region=region)
    args = parse_args(input, region, version, parameter, account_info)

    with Action('Generating Cloud Formation template..'):
        data = evaluate(input.copy(), args, account_info, force)
        cfjson = json.dumps(data, sort_keys=True, indent=4)

    stack_name = "{0}-{1}".format(input["SenzaInfo"]["StackName"], version)
    if len(stack_name) > 128:
        fatal_error('Error: Stack name "{}" cannot exceed 128 characters. '.format(stack_name) +
                    'Please choose another name/version.')

    parameters = []
    for name, parameter in data.get("Parameters", {}).items():
        parameters.append([name, getattr(args, name, None)])

    tags = {}
    for tag in input["SenzaInfo"].get('Tags', []):
        for key, value in tag.items():
            # # As the SenzaInfo is not evaluated, we explicitly evaluate the values here
            tags[key] = evaluate_template(value, info, [], args, account_info)

    tags.update({
        "Name": stack_name,
        "StackName": input["SenzaInfo"]["StackName"],
        "StackVersion": version
    })

    if "OperatorTopicId" in input["SenzaInfo"]:
        topic = input["SenzaInfo"]["OperatorTopicId"]
        topic_arn = resolve_topic_arn(region, topic)
        if not topic_arn:
            fatal_error('Error: SNS topic "{}" does not exist'.format(topic))
        topics = [topic_arn]
    else:
        topics = None

    capabilities = get_required_capabilities(data)

    cf = boto.cloudformation.connect_to_region(region)

    with Action('Creating Cloud Formation stack {}..'.format(stack_name)) as act:
        try:
            if dry_run:
                info('**DRY-RUN** {}'.format(topics))
            else:
                cf.create_stack(stack_name, template_body=cfjson, parameters=parameters, tags=tags,
                                notification_arns=topics, disable_rollback=disable_rollback, capabilities=capabilities)
        except boto.exception.BotoServerError as e:
            if e.error_code == 'AlreadyExistsException':
                act.fatal_error('Stack {} already exists. Please choose another version.'.format(stack_name))
            else:
                raise


@cli.command('print')
@click.argument('definition', type=DEFINITION)
@click.argument('version', callback=validate_version)
@click.argument('parameter', nargs=-1)
@region_option
@json_output_option
@click.option('-f', '--force', is_flag=True, help='Ignore failing validation checks')
def print_cfjson(definition, region, version, parameter, output, force):
    '''Print the generated Cloud Formation template'''
    input = definition
    region = get_region(region)
    check_credentials(region)
    account_info = AccountArguments(region=region)
    args = parse_args(input, region, version, parameter, account_info)
    data = evaluate(input.copy(), args, account_info, force)
    cfjson = json.dumps(data, sort_keys=True, indent=4)
    print_json(cfjson, output)


@cli.command()
@click.argument('stack_ref', nargs=-1)
@region_option
@click.option('--dry-run', is_flag=True, help='No-op mode: show what would be deleted')
@click.option('-f', '--force', is_flag=True, help='Allow deleting multiple stacks')
def delete(stack_ref, region, dry_run, force):
    '''Delete a single Cloud Formation stack'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)
    check_credentials(region)
    cf = boto.cloudformation.connect_to_region(region)

    if not stack_refs:
        raise click.UsageError('Please specify at least one stack')

    stacks = list(get_stacks(stack_refs, region))

    if len(stacks) > 1 and not dry_run and not force:
        fatal_error('Error: {} matching stacks found. '.format(len(stacks)) +
                    'Please use the "--force" flag if you really want to delete multiple stacks.')

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
@watchrefresh_option
@output_option
def resources(stack_ref, region, w, watch, output):
    '''Show all resources of a single Cloud Formation stack'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)
    check_credentials(region)
    cf = boto.cloudformation.connect_to_region(region)

    for _ in watching(w, watch):
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
@watchrefresh_option
@output_option
def events(stack_ref, region, w, watch, output):
    '''Show all Cloud Formation events for a single stack'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)
    check_credentials(region)
    cf = boto.cloudformation.connect_to_region(region)

    for _ in watching(w, watch):
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
                          [(t, get_template_description(t)) for t in sorted(templates)],
                          default='webapp')

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
        # ignore rate limit exceeded errors
        if e.code not in ('LoadBalancerNotFound', 'ValidationError', 'Throttling'):
            raise
    return instance_health


def get_instance_user_data(instance) -> dict:
    try:
        attrs = instance.get_attribute('userData')
        data_b64 = attrs['userData']
        data_yaml = base64.b64decode(data_b64)
        data_dict = yaml.load(data_yaml)
        return data_dict
    except Exception as e:  # there's just too many ways this can fail, catch 'em all
        sys.stderr.write('Failed to query instance user data: {}\n'.format(e))
    return {}


def get_instance_docker_image_source(instance) -> str:
    return get_instance_user_data(instance).get('source', '')


@cli.command()
@click.argument('stack_ref', nargs=-1)
@click.option('--all', is_flag=True, help='Show all instances, including instances not part of any stack')
@click.option('--terminated', is_flag=True, help='Show instances in TERMINATED state')
@click.option('-d', '--docker-image', is_flag=True, help='Show docker image source for every instance listed')
@region_option
@output_option
@watch_option
@watchrefresh_option
def instances(stack_ref, all, terminated, docker_image, region, output, w, watch):
    '''List the stack's EC2 instances'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)
    check_credentials(region)

    conn = boto.ec2.connect_to_region(region)
    elb = boto.ec2.elb.connect_to_region(region)

    if all:
        filters = None
    else:
        # filter out instances not part of any stack
        filters = {'tag-key': 'aws:cloudformation:stack-name'}

    opt_docker_column = ' docker_source' if docker_image else ''

    for _ in watching(w, watch):
        rows = []

        for instance in conn.get_only_instances(filters=filters):
            cf_stack_name = instance.tags.get('aws:cloudformation:stack-name')
            stack_name = instance.tags.get('StackName')
            stack_version = instance.tags.get('StackVersion')
            if not stack_refs or matches_any(cf_stack_name, stack_refs):
                instance_health = get_instance_health(elb, cf_stack_name)
                if instance.state.upper() != 'TERMINATED' or terminated:

                    docker_source = get_instance_docker_image_source(instance) if docker_image else ''

                    rows.append({'stack_name': stack_name or '',
                                 'version': stack_version or '',
                                 'resource_id': instance.tags.get('aws:cloudformation:logical-id'),
                                 'instance_id': instance.id,
                                 'public_ip': instance.ip_address,
                                 'private_ip': instance.private_ip_address,
                                 'state': instance.state.upper().replace('-', '_'),
                                 'lb_status': instance_health.get(instance.id),
                                 'docker_source': docker_source,
                                 'launch_time': parse_time(instance.launch_time)})

        rows.sort(key=lambda r: (r['stack_name'], r['version'], r['instance_id']))

        with OutputFormat(output):
            print_table(('stack_name version resource_id instance_id public_ip ' +
                         'private_ip state lb_status{} launch_time'.format(opt_docker_column)).split(),
                        rows, styles=STYLES, titles=TITLES)


@cli.command()
@click.argument('stack_ref', nargs=-1)
@region_option
@output_option
@watch_option
@watchrefresh_option
def status(stack_ref, region, output, w, watch):
    '''Show stack status information'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)
    check_credentials(region)

    conn = boto.ec2.connect_to_region(region)
    elb = boto.ec2.elb.connect_to_region(region)
    cf = boto.cloudformation.connect_to_region(region)

    for _ in watching(w, watch):
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
@watchrefresh_option
def domains(stack_ref, region, output, w, watch):
    '''List the stack's Route53 domains'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)
    check_credentials(region)

    cf = boto.cloudformation.connect_to_region(region)
    route53 = boto.route53.connect_to_region(region)

    records_by_name = {}

    for _ in watching(w, watch):
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
    check_credentials(region)

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
    check_credentials(region)

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
        creation_time = parse_time(image.creationDate)
        row['creation_time'] = creation_time
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
        if creation_time > cutoff.timestamp() or row['total_instances']:
            rows.append(row)

    rows.sort(key=lambda x: x.get('name'))
    with OutputFormat(output):
        cols = 'id name owner_id description stacks total_instances creation_time'
        if show_instances:
            cols = cols.replace('total_instances', 'instances')
        print_table(cols.split(), rows, titles=TITLES, max_column_widths=MAX_COLUMN_WIDTHS)


def is_ip_address(x: str):
    '''
    >>> is_ip_address(None)
    False

    >>> is_ip_address('127.0.0.1')
    True
    '''
    try:
        ipaddress.ip_address(x)
        return True
    except:
        return False


def get_console_line_style(line: str):
    '''
    >>> get_console_line_style('foo')
    {}

    >>> get_console_line_style('ERROR:')['fg']
    'red'

    >>> get_console_line_style('WARNING:')['fg']
    'yellow'

    >>> get_console_line_style('SUCCESS:')['fg']
    'green'

    >>> get_console_line_style('INFO:')['bold']
    True
    '''

    if 'ERROR:' in line:
        return {'fg': 'red', 'bold': True}
    elif 'WARNING:' in line:
        return {'fg': 'yellow', 'bold': True}
    elif 'SUCCESS:' in line:
        return {'fg': 'green', 'bold': True}
    elif 'INFO:' in line:
        return {'bold': True}
    else:
        return {}


def print_console(line: str):
    style = get_console_line_style(line)
    click.secho(line, **style)


@cli.command()
@click.argument('instance_or_stack_ref', nargs=-1)
@click.option('-l', '--limit', help='Show last N lines of console output (default: 25)',
              type=int, default=25, metavar='N')
@region_option
@watch_option
@watchrefresh_option
def console(instance_or_stack_ref, limit, region, w, watch):
    '''Print EC2 instance console output.

    INSTANCE_OR_STACK_REF can be an instance ID, private IP address or stack name/version.'''

    if all(x.startswith('i-') for x in instance_or_stack_ref):
        stack_refs = None
        filters = {'instance-id': list(instance_or_stack_ref)}
    elif all(is_ip_address(x) for x in instance_or_stack_ref):
        stack_refs = None
        filters = {'private-ip-address': list(instance_or_stack_ref)}
    else:
        stack_refs = get_stack_refs(instance_or_stack_ref)
        # filter out instances not part of any stack
        filters = {'tag-key': 'aws:cloudformation:stack-name'}

    region = get_region(region)
    check_credentials(region)

    conn = boto.ec2.connect_to_region(region)

    for _ in watching(w, watch):

        for instance in conn.get_only_instances(filters=filters):
            cf_stack_name = instance.tags.get('aws:cloudformation:stack-name')
            if not stack_refs or matches_any(cf_stack_name, stack_refs):
                output = conn.get_console_output(instance.id)
                click.secho('Showing last {} lines of {}..'.format(limit, instance.private_ip_address or instance.id),
                            bold=True)
                if output.output:
                    for line in output.output.decode('utf-8', errors='replace').split('\n')[-limit:]:
                        print_console(line)


@cli.command()
@click.argument('stack_ref', nargs=-1)
@region_option
@json_output_option
def dump(stack_ref, region, output):
    '''Dump Cloud Formation template of existing stack'''
    stack_refs = get_stack_refs(stack_ref)
    region = get_region(region)
    check_credentials(region)

    conn = boto.cloudformation.connect_to_region(region)

    for stack in get_stacks(stack_refs, region):
        result = conn.get_template(stack.stack_name)
        template = result['GetTemplateResponse']['GetTemplateResult']['TemplateBody']
        print_json(template, output)


def main():
    handle_exceptions(cli)()


if __name__ == "__main__":
    main()
