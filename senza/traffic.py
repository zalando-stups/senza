from boto.route53.record import ResourceRecordSets
import click
from clickclick import warning, action, ok, print_table, Action
import collections
from .aws import get_stacks, StackReference

import boto.route53

PERCENT_RESOLUTION = 2
FULL_PERCENTAGE = PERCENT_RESOLUTION * 100


def get_weights(dns_name: str, identifier: str, rr: ResourceRecordSets, all_identifiers) -> ({str: int}, int, int):
    """
    For the given dns_name, get the dns record weights from provided dns record set
    followed by partial count and partial weight sum.
    Here partial means without the element that we are operating now on.
    """
    partial_count = 0
    partial_sum = 0
    known_record_weights = {}
    for r in rr:
        if r.type == 'CNAME' and r.name == dns_name:
            if r.weight:
                w = int(r.weight)
            else:
                w = 0
            known_record_weights[r.identifier] = w
            if r.identifier != identifier and w > 0:
                # we should ignore all versions that do not get any traffic
                # not to put traffic on the disabled versions when redistributing traffic weights
                partial_sum += w
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


def set_new_weights(dns_name, identifier, lb_dns_name: str, new_record_weights, percentage, rr):
    action('Setting weights for {dns_name}..', **vars())
    did_the_upsert = False
    for r in rr:
        if r.type == 'CNAME' and r.name == dns_name:
            w = new_record_weights[r.identifier]
            if w:
                if int(r.weight) != w:
                    r.weight = w
                    rr.add_change_record('UPSERT', r)
                if identifier == r.identifier:
                    did_the_upsert = True
            else:
                rr.add_change_record('DELETE', r)
    if new_record_weights[identifier] > 0 and not did_the_upsert:
        change = rr.add_change('CREATE', dns_name, 'CNAME', ttl=20, identifier=identifier,
                               weight=new_record_weights[identifier])
        change.add_value(lb_dns_name)
    if rr.changes:
        rr.commit()
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

    print_table('stack_name version identifier old_weight% delta compensation new_weight% current'.split(),
                sorted(rows, key=lambda x: identifier_versions.get(x['identifier'], '')))


class StackVersion(collections.namedtuple('StackVersion', 'name version domain lb_dns_name')):
    @property
    def identifier(self):
        return '{}-{}'.format(self.name, self.version)

    @property
    def dns_name(self):
        return self.domain + '.'


def get_stack_versions(stack_name: str, region: str):
    cf = boto.cloudformation.connect_to_region(region)
    for stack in get_stacks([StackReference(name=stack_name, version=None)], region):
        if stack.stack_status in ('ROLLBACK_COMPLETE', 'CREATE_FAILED'):
            continue
        details = cf.describe_stacks(stack.stack_id)[0]
        resources = cf.describe_stack_resources(stack.stack_id)
        lb_dns_name = None
        domain = None
        for res in resources:
            if res.resource_type == 'AWS::ElasticLoadBalancing::LoadBalancer':
                elb = boto.ec2.elb.connect_to_region(region)
                lbs = elb.get_all_load_balancers([res.physical_resource_id])
                lb_dns_name = lbs[0].dns_name
            elif res.resource_type == 'AWS::Route53::RecordSet':
                if 'version' not in res.logical_resource_id.lower():
                    domain = res.physical_resource_id
        yield StackVersion(stack_name, details.tags.get('StackVersion'), domain, lb_dns_name)


def get_version(versions: list, version: str):
    for ver in versions:
        if ver.version == version:
            return ver
    raise click.UsageError('Stack version {} not found'.format(version))


def get_zone(region: str, domain: str):
    dns_conn = boto.route53.connect_to_region(region)
    zone = dns_conn.get_zone(domain + '.')
    if not zone:
        raise ValueError('Zone {} not found'.format(domain))
    return zone


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

    domain = version.domain.split('.', 1)[1]
    zone = get_zone(region, domain)
    rr = zone.get_records()
    known_record_weights, partial_count, partial_sum = get_weights(version.dns_name, version.identifier, rr,
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
    identifier_versions = collections.OrderedDict(
        (version.identifier, version.version) for version in versions)
    version = get_version(versions, stack_ref.version)

    identifier = version.identifier

    if not version.domain:
        raise click.UsageError('Stack {} version {} has no domain'.format(version.name, version.version))

    domain = version.domain.split('.', 1)[1]
    zone = get_zone(region, domain)
    rr = zone.get_records()
    percentage = int(percentage * PERCENT_RESOLUTION)
    known_record_weights, partial_count, partial_sum = get_weights(version.dns_name, identifier, rr,
                                                                   identifier_versions.keys())

    if partial_count == 0 and percentage == 0:
        # disable the last remaining version
        new_record_weights = {i: 0 for i in known_record_weights.keys()}
        ok(msg='DNS record "{dns_name}" will be removed from that stack'.format(dns_name=version.dns_name))
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
        dump_traffic_changes(stack_ref.name,
                             identifier,
                             identifier_versions,
                             known_record_weights,
                             new_record_weights,
                             compensations,
                             deltas)
    set_new_weights(version.dns_name, identifier, version.lb_dns_name, new_record_weights, percentage, rr)
