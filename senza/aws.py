import collections
import datetime
import functools
import boto.cloudformation
import boto.ec2
import boto.iam
import time


def get_security_group(region: str, sg_name: str):
    conn = boto.ec2.connect_to_region(region)
    all_security_groups = conn.get_all_security_groups()
    for _sg in all_security_groups:
        if _sg.name == sg_name:
            return _sg


def find_ssl_certificate_arn(region, pattern):
    '''Find the a matching SSL cert and return its ARN'''
    iam_conn = boto.iam.connect_to_region(region)
    response = iam_conn.list_server_certs()
    response = response['list_server_certificates_response']
    certs = response['list_server_certificates_result']['server_certificate_metadata_list']
    candidates = set()
    for cert in certs:
        # only consider matching SSL certs or use the only one available
        if pattern in cert['server_certificate_name'] or len(certs) == 1:
            candidates.add(cert['arn'])
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


def resolve_topic_arn(region, topic):
    '''
    >>> resolve_topic_arn(None, 'arn:123')
    'arn:123'
    '''
    if topic.startswith('arn:'):
        topic_arn = topic
    else:
        # resolve topic name to ARN
        sns = boto.sns.connect_to_region(region)
        response = sns.get_all_topics()
        topic_arn = False
        for obj in response['ListTopicsResponse']['ListTopicsResult']['Topics']:
            if obj['TopicArn'].endswith(topic):
                topic_arn = obj['TopicArn']

    return topic_arn


@functools.total_ordering
class SenzaStackSummary:
    def __init__(self, stack):
        self.stack = stack
        parts = stack.stack_name.rsplit('-', 1)
        self.name = parts[0]
        if len(parts) > 1:
            self.version = parts[1]
        else:
            self.version = ''

    def __getattr__(self, item):
        if item in self.__dict__:
            return self.__dict__[item]
        return getattr(self.stack, item)

    def __lt__(self, other):
        def key(v):
            return (v.name, v.version)
        return key(self) < key(other)

    def __eq__(self, other):
        return self.stack_name == other.stack_name


def get_stacks(stack_refs: list, region, all=False):
    cf = boto.cloudformation.connect_to_region(region)
    if all:
        status_filter = None
    else:
        status_filter = [st for st in cf.valid_states if st != 'DELETE_COMPLETE']
    stacks = cf.list_stacks(stack_status_filters=status_filter)
    for stack in stacks:
        if not stack_refs or matches_any(stack.stack_name, stack_refs):
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


class StackReference(collections.namedtuple('StackReference', 'name version')):
    def cf_stack_name(self):
        return '{}-{}'.format(self.name, self.version)
