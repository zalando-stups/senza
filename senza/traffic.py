import collections
from json import JSONEncoder

import boto3
import click
import dns.resolver
from clickclick import Action, action, ok, print_table, warning

from .aws import StackReference, get_stacks, get_tag
from .manaus.elb import ELB
from .manaus.route53 import (RecordType, Route53, Route53HostedZone,
                             Route53Record, convert_domain_records_to_alias)

PERCENT_RESOLUTION = 2
FULL_PERCENTAGE = PERCENT_RESOLUTION * 100
DNS_RR_CACHE = {}
DNS_ZONE_CACHE = {}


def get_weights(dns_names: list, identifier: str, all_identifiers) -> ({str: int}, int, int):
    """
    For the given dns_name, get the dns record weights from provided dns record set
    followed by partial count and partial weight sum.
    Here partial means without the element that we are operating now on.
    """
    partial_count = 0
    partial_sum = 0
    known_record_weights = {}
    for dns_name in dns_names:
        for record in Route53.get_records(name=dns_name):
            if record.type in [RecordType.CNAME, RecordType.A, RecordType.AAAA]:
                try:
                    if record.weight:
                        weight = record.weight
                    else:
                        weight = 0
                except KeyError:
                    continue
                else:
                    known_record_weights[record.set_identifier] = weight
                    if record.set_identifier != identifier and weight > 0:
                        # we should ignore all versions that do not get any
                        # traffic to not give traffic to disabled versions when
                        # redistributing traffic weights
                        partial_sum += weight
                        partial_count += 1
    if identifier not in known_record_weights:
        known_record_weights[identifier] = 0
    for ident in all_identifiers:
        if ident not in known_record_weights:
            known_record_weights[ident] = 0
    return known_record_weights, partial_count, partial_sum


def calculate_new_weights(delta, identifier, known_record_weights, percentage):
    new_record_weights = {}
    deltas = {}
    for i, w in known_record_weights.items():
        if i == identifier:
            n = percentage
        else:
            if percentage == FULL_PERCENTAGE:
                # other versions should be disabled if 100% of traffic is ordered for our version
                n = 0
            else:
                if w > 0:
                    # if old weight is not zero
                    # do not allow it to be pushed below 1
                    n = int(max(1, w + delta))
                else:
                    # do not touch versions that had not been getting traffic before
                    n = 0
        new_record_weights[i] = n
        deltas[i] = n - known_record_weights[i]
    return new_record_weights, deltas


def compensate(calculation_error, compensations, identifier, new_record_weights, partial_count,
               percentage, identifier_versions):
    """
    Compensate for the rounding errors as well as for the fact, that we do not allow to bring down the minimal weights
    lower then minimal possible value not to disable traffic from the minimally configured versions (1) and
    we do not allow to add any values to the already disabled versions (0).
    """
    # distribute the error on the versions, other then the current one
    assert partial_count
    part = calculation_error / partial_count
    if part > 0:
        part = int(max(1, part))
    else:
        part = int(min(-1, part))
    # avoid changing the older version distributions
    for i in sorted(new_record_weights.keys(), key=lambda x: identifier_versions[x], reverse=True):
        if i == identifier:
            continue
        nw = new_record_weights[i] + part
        if nw <= 0:
            # do not remove the traffic from the minimal traffic versions
            continue
        new_record_weights[i] = nw
        calculation_error -= part
        compensations[i] = part
        if calculation_error == 0:
            break
    if calculation_error != 0:
        adjusted_percentage = percentage + calculation_error
        compensations[identifier] = calculation_error
        calculation_error = 0
        warning(
            ("Changing given percentage from {} to {} " +
             "because all other versions are already getting the possible minimum traffic").format(
                percentage / PERCENT_RESOLUTION, adjusted_percentage / PERCENT_RESOLUTION))
        percentage = adjusted_percentage
        new_record_weights[identifier] = percentage
    assert calculation_error == 0
    return percentage


def set_new_weights(dns_names: list, identifier, lb_dns_name: str, new_record_weights, percentage):
    action('Setting weights for {dns_names}..', dns_names=', '.join(dns_names))
    dns_changes = collections.defaultdict(list)
    for idx, dns_name in enumerate(dns_names):
        domain = dns_name.split('.', 1)[1]
        hosted_zone = Route53HostedZone.get_by_domain_name(domain)
        did_the_upsert = False

        convert_domain_records_to_alias(dns_name)

        for r in Route53.get_records(name=dns_name):
            if r.type in [RecordType.CNAME, RecordType.A, RecordType.AAAA]:
                w = new_record_weights[r.set_identifier]
                if w:
                    if int(r.weight) != w:
                        r.weight = w
                        dns_changes[hosted_zone.id].append({'Action': 'UPSERT',
                                                            'ResourceRecordSet': r.boto_dict})
                    if identifier == r.set_identifier:
                        did_the_upsert = True
                else:
                    if dns_changes.get(hosted_zone.id) is None:
                        dns_changes[hosted_zone.id] = []
                    dns_changes[hosted_zone.id].append({'Action': 'DELETE',
                                                        'ResourceRecordSet': r.boto_dict.copy()})
        if new_record_weights[identifier] > 0 and not did_the_upsert:
            elb = ELB.get_by_dns_name(lb_dns_name[idx])
            record = Route53Record(name=dns_name,
                                   type=RecordType.A,
                                   set_identifier=identifier,
                                   weight=new_record_weights[identifier],
                                   alias_target={"HostedZoneId": elb.hosted_zone.id,
                                                 "DNSName": lb_dns_name[idx],
                                                 "EvaluateTargetHealth": True})
            dns_changes[hosted_zone.id].append({'Action': 'UPSERT',
                                                'ResourceRecordSet': record.boto_dict})
    if dns_changes:
        route53 = boto3.client('route53')
        for hosted_zone_id, change in dns_changes.items():
            route53.change_resource_record_sets(HostedZoneId=hosted_zone_id,
                                                ChangeBatch={'Comment': 'Weight change of {}'.format(hosted_zone_id),
                                                             'Changes': change})
        if sum(new_record_weights.values()) == 0:
            ok(' DISABLED')
        else:
            ok()
    else:
        ok(' not changed')


def dump_traffic_changes(stack_name: str,
                         identifier: str,
                         identifier_versions: {str: str},
                         known_record_weights: {str: int},
                         new_record_weights: {str: int},
                         compensations: {str: int},
                         deltas: {str: int}
                         ):
    """
    dump changes to the traffic settings for the given versions
    """
    rows = [
        {
            'stack_name': stack_name,
            'version': identifier_versions.get(i),
            'identifier': i,
            'old_weight%': known_record_weights.get(i),
            # 'delta': (delta if new_record_weights[i] else 0 if i != identifier else forced_delta),
            'delta': deltas[i],
            'compensation': compensations.get(i),
            'new_weight%': new_record_weights.get(i),
        } for i in known_record_weights.keys()
    ]

    full_switch = max(new_record_weights.values()) == FULL_PERCENTAGE

    for r in rows:
        d = r['delta']
        c = r['compensation']
        if full_switch and not d and c:
            d = -c
        r['delta'] = (d / PERCENT_RESOLUTION) if d else None
        r['old_weight%'] /= PERCENT_RESOLUTION
        r['new_weight%'] /= PERCENT_RESOLUTION
        r['compensation'] = (c / PERCENT_RESOLUTION) if c else None
        if identifier == r['identifier']:
            r['current'] = '<'

    return sorted(rows, key=lambda x: identifier_versions.get(x['identifier'], ''))


def print_traffic_changes(message: list):
    print_table('stack_name version identifier old_weight% delta compensation new_weight% current'.split(), message)


class StackVersion(collections.namedtuple('StackVersion', 'name version domain lb_dns_name notification_arns')):
    @property
    def identifier(self):
        return '{}-{}'.format(self.name, self.version)

    @property
    def dns_name(self):
        return ['{}.'.format(x) for x in self.domain]


def get_stack_versions(stack_name: str, region: str):
    cf = boto3.resource('cloudformation', region)
    for stack in get_stacks([StackReference(name=stack_name, version=None)], region):
        if stack.StackStatus in ('ROLLBACK_COMPLETE', 'CREATE_FAILED'):
            continue
        details = cf.Stack(stack.StackId)
        lb_dns_name = []
        domain = []
        notification_arns = details.notification_arns
        for res in details.resource_summaries.all():
            if res.resource_type == 'AWS::ElasticLoadBalancing::LoadBalancer':
                elb = boto3.client('elb', region)
                lbs = elb.describe_load_balancers(LoadBalancerNames=[res.physical_resource_id])
                lb_dns_name.append(lbs['LoadBalancerDescriptions'][0]['DNSName'])
            elif res.resource_type == 'AWS::Route53::RecordSet':
                if 'version' not in res.logical_id.lower():
                    domain.append(res.physical_resource_id)
        yield StackVersion(stack_name, get_tag(details.tags, 'StackVersion'), domain, lb_dns_name, notification_arns)


def get_version(versions: list, version: str):
    for ver in versions:
        if ver.version == version:
            return ver
    raise click.UsageError('Stack version {} not found'.format(version))


def get_records(domain: str):
    domain = '{}.'.format(domain.rstrip('.'))
    if DNS_RR_CACHE.get(domain) is None:
        hosted_zone = Route53HostedZone.get_by_domain_name(domain)
        route53 = boto3.client('route53')
        result = route53.list_resource_record_sets(HostedZoneId=hosted_zone.id)
        records = result['ResourceRecordSets']
        while result['IsTruncated']:
            recordfilter = {'HostedZoneId': hosted_zone.id,
                            'StartRecordName': result['NextRecordName'],
                            'StartRecordType': result['NextRecordType']
                            }
            if result.get('NextRecordIdentifier'):
                recordfilter['StartRecordIdentifier'] = result.get('NextRecordIdentifier')

            result = route53.list_resource_record_sets(**recordfilter)
            records.extend(result['ResourceRecordSets'])
        DNS_RR_CACHE[domain] = records
    return DNS_RR_CACHE[domain]


def print_version_traffic(stack_ref: StackReference, region):
    versions = list(get_stack_versions(stack_ref.name, region))
    identifier_versions = collections.OrderedDict(
        (version.identifier, version.version) for version in versions)
    if stack_ref.version:
        version = get_version(versions, stack_ref.version)
    elif versions:
        version = versions[0]
    else:
        raise click.UsageError('No stack version of "{}" found'.format(stack_ref.name))

    if not version.domain:
        raise click.UsageError('Stack {} version {} has no domain'.format(version.name, version.version))

    known_record_weights, partial_count, partial_sum = get_weights(version.dns_name, version.identifier,
                                                                   identifier_versions.keys())

    rows = [
        {
            'stack_name': version.name,
            'version': identifier_versions.get(i),
            'identifier': i,
            'weight%': known_record_weights[i],
        } for i in known_record_weights.keys()
    ]

    for r in rows:
        r['weight%'] /= PERCENT_RESOLUTION
        if version.identifier == r['identifier']:
            r['current'] = '<'

    cols = 'stack_name version identifier weight%'.split()
    if stack_ref.version:
        cols.append('current')
    print_table(cols,
                sorted(rows, key=lambda x: identifier_versions.get(x['identifier'], '')))


def change_version_traffic(stack_ref: StackReference, percentage: float, region):
    versions = list(get_stack_versions(stack_ref.name, region))
    arns = []
    for v in versions:
        arns = arns + v.notification_arns
    identifier_versions = collections.OrderedDict(
        (version.identifier, version.version) for version in versions)
    version = get_version(versions, stack_ref.version)

    identifier = version.identifier

    if not version.domain:
        raise click.UsageError('Stack {} version {} has no domain'.format(version.name, version.version))

    percentage = int(percentage * PERCENT_RESOLUTION)
    known_record_weights, partial_count, partial_sum = get_weights(version.dns_name, identifier,
                                                                   identifier_versions.keys())

    if partial_count == 0 and percentage == 0:
        # disable the last remaining version
        new_record_weights = {i: 0 for i in known_record_weights.keys()}
        message = 'DNS record "{dns_name}" will be removed from that stack'.format(dns_name=version.dns_name)
        ok(msg=message)
    else:
        with Action('Calculating new weights..'):
            compensations = {}
            if partial_count:
                delta = int((FULL_PERCENTAGE - percentage - partial_sum) / partial_count)
            else:
                delta = 0
                if percentage > 0:
                    # will put the only last version to full traffic percentage
                    compensations[identifier] = FULL_PERCENTAGE - percentage
                    percentage = int(FULL_PERCENTAGE)
            new_record_weights, deltas = calculate_new_weights(delta, identifier, known_record_weights, percentage)
            total_weight = sum(new_record_weights.values())
            calculation_error = FULL_PERCENTAGE - total_weight
            if calculation_error and calculation_error < FULL_PERCENTAGE:
                percentage = compensate(calculation_error, compensations, identifier,
                                        new_record_weights, partial_count, percentage, identifier_versions)
            assert sum(new_record_weights.values()) == FULL_PERCENTAGE
        message = dump_traffic_changes(stack_ref.name,
                                       identifier,
                                       identifier_versions,
                                       known_record_weights,
                                       new_record_weights,
                                       compensations,
                                       deltas)
        print_traffic_changes(message)
        inform_sns(arns, message, region)
    set_new_weights(version.dns_name, identifier, version.lb_dns_name, new_record_weights, percentage)


def inform_sns(arns: list, message: str, region):
    jsonizer = JSONEncoder()
    sns_topics = set(arns)
    sns = boto3.client('sns', region_name=region)
    for sns_topic in sns_topics:
        sns.publish(TopicArn=sns_topic, Subject="SenzaTrafficRedirect", Message=jsonizer.encode((message)))


def resolve_to_ip_addresses(dns_name: str) -> set:
    """
    Try to resolve the given DNS name to IPv4 addresses and return empty set on ANY error.
    """
    try:
        answers = dns.resolver.query(dns_name, 'A')
    except:
        return set()
    else:
        return {answer.address for answer in answers}
