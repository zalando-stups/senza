import collections
import datetime
import functools
import time
import boto3
from botocore.exceptions import ClientError


def get_security_group(region: str, sg_name: str):
    ec2 = boto3.resource('ec2', region)
    try:
        return list(ec2.security_groups.filter(GroupNames=[sg_name]))[0]
    except ClientError as e:
        if e.response['Error']['Code'] == 'InvalidGroup.NotFound':
            return None
        elif e.response['Error']['Code'] == 'VPCIdNotSpecified':
            # no Default VPC, we must use the lng way...
            for sg in ec2.security_groups.all():
                # FIXME: What if we have 2 VPC, with a SG with the same name?!
                if sg.group_name == sg_name:
                    return sg
            return None
        else:
            raise


def resolve_security_groups(security_groups: list, region: str):
    result = []
    for security_group in security_groups:
        if isinstance(security_group, dict):
            result.append(security_group)
        elif security_group.startswith('sg-'):
            result.append(security_group)
        else:
            sg = get_security_group(region, security_group)
            if not sg:
                raise ValueError('Security Group "{}" does not exist'.format(security_group))
            result.append(sg.id)

    return result


def find_ssl_certificate_arn(region, pattern):
    '''Find the a matching SSL cert and return its ARN'''
    iam = boto3.resource('iam')
    candidates = set()
    certs = list(iam.server_certificates.all())
    for cert in certs:
        # only consider matching SSL certs or use the only one available
        if pattern == cert.name or len(certs) == 1:
            candidates.add(cert.server_certificate_metadata['Arn'])
    if candidates:
        # return first match (alphabetically sorted
        return sorted(candidates)[0]
    else:
        return None


def parse_time(s: str) -> float:
    '''
    >>> parse_time('2015-04-14T19:09:01.000Z') > 0
    True
    '''
    try:
        utc = datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%S.%fZ')
        ts = time.time()
        utc_offset = datetime.datetime.fromtimestamp(ts) - datetime.datetime.utcfromtimestamp(ts)
        local = utc + utc_offset
        return local.timestamp()
    except:
        return None


def get_required_capabilities(data: dict):
    '''Get capabilities for a given cloud formation template for the "create_stack" call

    >>> get_required_capabilities({})
    []

    >>> get_required_capabilities({'Resources': {'MyRole': {'Type': 'AWS::IAM::Role', 'a': 'b'}}})
    ['CAPABILITY_IAM']
    '''
    capabilities = []
    for logical_id, config in data.get('Resources', {}).items():
        if config.get('Type').startswith('AWS::IAM'):
            capabilities.append('CAPABILITY_IAM')
    return capabilities


def resolve_topic_arn(region, topic_name):
    '''
    >>> resolve_topic_arn(None, 'arn:123')
    'arn:123'
    '''
    topic_arn = None
    if topic_name.startswith('arn:'):
        topic_arn = topic_name
    else:
        # resolve topic name to ARN
        sns = boto3.resource('sns', region)
        for topic in sns.topics.all():
            if topic.arn.endswith(':{}'.format(topic_name)):
                topic_arn = topic.arn

    return topic_arn


@functools.total_ordering
class SenzaStackSummary:
    def __init__(self, stack):
        self.stack = stack
        parts = stack['StackName'].rsplit('-', 1)
        self.name = parts[0]
        if len(parts) > 1:
            self.version = parts[1]
        else:
            self.version = ''

    def __getattr__(self, item):
        if item in self.__dict__:
            return self.__dict__[item]
        return self.stack.get(item)

    def __lt__(self, other):
        def key(v):
            return (v.name, v.version)
        return key(self) < key(other)

    def __eq__(self, other):
        return self.stack['StackName'] == other.stack['StackName']


def get_stacks(stack_refs: list, region, all=False):
    # boto3.resource('cf')-stacks.filter() doesn't support status_filter, only StackName
    cf = boto3.client('cloudformation', region)
    if all:
        status_filter = []
    else:
        # status_filter = [st for st in cf.valid_states if st != 'DELETE_COMPLETE']
        status_filter = [
            "CREATE_IN_PROGRESS",
            "CREATE_FAILED",
            "CREATE_COMPLETE",
            "ROLLBACK_IN_PROGRESS",
            "ROLLBACK_FAILED",
            "ROLLBACK_COMPLETE",
            "DELETE_IN_PROGRESS",
            "DELETE_FAILED",
            # "DELETE_COMPLETE",
            "UPDATE_IN_PROGRESS",
            "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
            "UPDATE_COMPLETE",
            "UPDATE_ROLLBACK_IN_PROGRESS",
            "UPDATE_ROLLBACK_FAILED",
            "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS",
            "UPDATE_ROLLBACK_COMPLETE"
        ]
    for stack in cf.list_stacks(StackStatusFilter=status_filter)['StackSummaries']:
        if not stack_refs or matches_any(stack['StackName'], stack_refs):
            yield SenzaStackSummary(stack)


def matches_any(cf_stack_name: str, stack_refs: list):
    '''
    >>> matches_any(None, [StackReference(name='foobar', version=None)])
    False

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
        elif not ref.version and (cf_stack_name or '').rsplit('-', 1)[0] == ref.name:
            return True
    return False


def get_tag(tags: list, key: str, default=None):
    '''
    >>> tags = [{'Key': 'aws:cloudformation:stack-id',
    ...          'Value': 'arn:aws:cloudformation:eu-west-1:123:stack/test-123'},
    ...         {'Key': 'Name',
    ...          'Value': 'test-123'},
    ...         {'Key': 'StackVersion',
    ...          'Value': '123'}]
    >>> get_tag(tags, 'StackVersion')
    '123'
    >>> get_tag(tags, 'aws:cloudformation:stack-id')
    'arn:aws:cloudformation:eu-west-1:123:stack/test-123'
    >>> get_tag(tags, 'notfound') is None
    True
    '''
    if isinstance(tags, list):
        found = [tag['Value'] for tag in tags if tag['Key'] == key]
        if len(found):
            return found[0]
    return default


def get_account_id():
    conn = boto3.client('iam')
    try:
        own_user = conn.get_user()['User']
    except:
        own_user = None
    if not own_user:
        roles = conn.list_roles()['Roles']
        if not roles:
            users = conn.list_users()['Users']
            if not users:
                saml = conn.list_saml_providers()['SAMLProviderList']
                if not saml:
                    return None
                else:
                    arn = [s['Arn'] for s in saml][0]
            else:
                arn = [u['Arn'] for u in users][0]
        else:
            arn = [r['Arn'] for r in roles][0]
    else:
        arn = own_user['Arn']
    account_id = arn.split(':')[4]
    return account_id


def get_account_alias():
    conn = boto3.client('iam')
    return conn.list_account_aliases()['AccountAliases'][0]


class StackReference(collections.namedtuple('StackReference', 'name version')):
    def cf_stack_name(self):
        return '{}-{}'.format(self.name, self.version)
