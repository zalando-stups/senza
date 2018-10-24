"""
Functions related to Traffic management
"""

import collections
from json import JSONEncoder
from typing import Dict, Iterator

import boto3
import click
import dns.resolver
from clickclick import Action, action, ok, print_table, warning

from .aws import StackReference, get_stacks, get_tag
from .manaus import ClientError
from .manaus.boto_proxy import BotoClientProxy
from .manaus.cloudformation import CloudFormationStack, ResourceType
from .manaus.exceptions import ELBNotFound, StackNotFound, StackNotUpdated
from .manaus.route53 import (
    RecordType,
    Route53,
    Route53HostedZone,
    convert_cname_records_to_alias,
)
from .manaus.utils import extract_client_error_code

PERCENT_RESOLUTION = 2
FULL_PERCENTAGE = PERCENT_RESOLUTION * 100
DNS_RR_CACHE = {}
DNS_ZONE_CACHE = {}


def get_weights(
    dns_names: list, identifier: str, all_identifiers
) -> ({str: int}, int, int):
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

    partial_count, partial_sum = get_partial_sum_partial_count(
        dns_names, identifier, all_identifiers
    )
    if identifier not in known_record_weights:
        known_record_weights[identifier] = 0
    for ident in all_identifiers:
        if ident not in known_record_weights:
            known_record_weights[ident] = 0
    return known_record_weights, partial_count, partial_sum


def get_partial_sum_partial_count(
    dns_names: list, identifier: str, all_identifiers
) -> ({str: int}, int, int):
    """
    Get weight and count for all stacks that have traffics
    excluding the element we are we are working on.

    We should ignore all versions that do not get any
    traffic to not give traffic to disabled versions when
    redistributing traffic weights
    """
    partial_count = 0
    partial_sum = 0
    dns_name = dns_names[0]
    for record in Route53.get_records(name=dns_name):
        if record.set_identifier != identifier and record.weight > 0:
            partial_sum += record.weight
            partial_count += 1

    return partial_count, partial_sum


def calculate_new_weights(delta, identifier, known_record_weights, percentage):
    """
    Calculates the new weights for the all the Route53 records
    """
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


def compensate(
    calculation_error,
    compensations,
    identifier,
    new_record_weights,
    partial_count,
    percentage,
    identifier_versions,
):
    """
    Compensate for the rounding errors as well as for the fact, that we do not
    allow to bring down the minimal weights lower then minimal possible value
    not to disable traffic from the minimally configured versions (1) and
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
    for i in sorted(
        new_record_weights.keys(), key=lambda x: identifier_versions[x], reverse=True
    ):
        if i == identifier:
            continue
        new_weight = new_record_weights[i] + part
        if new_weight <= 0:
            # do not remove the traffic from the minimal traffic versions
            continue
        new_record_weights[i] = new_weight
        calculation_error -= part
        compensations[i] = part
        if calculation_error == 0:
            break
    if calculation_error != 0:
        adjusted_percentage = percentage + calculation_error
        compensations[identifier] = calculation_error
        calculation_error = 0
        warning(
            (
                "Changing given percentage from {} to {} "
                + "because all other versions are already getting the possible minimum traffic"
            ).format(
                percentage / PERCENT_RESOLUTION,
                adjusted_percentage / PERCENT_RESOLUTION,
            )
        )
        percentage = adjusted_percentage
        new_record_weights[identifier] = percentage
    assert calculation_error == 0
    return percentage


def set_new_weights(
    dns_names: list, old_record_weights: Dict, new_record_weights: Dict, region: str
):
    action("Setting weights for {dns_names}..", dns_names=", ".join(dns_names))
    changed = False
    updates = {}
    for idx, dns_name in enumerate(dns_names):
        domain = dns_name.split(".", 1)[1]
        hosted_zone = Route53HostedZone.get_by_domain_name(domain)
        convert_cname_records_to_alias(dns_name)

        for stack_name, percentage in new_record_weights.items():
            if old_record_weights[stack_name] == percentage:
                # Stack weight will not change
                continue
            try:
                if stack_name not in updates.keys():
                    stack = CloudFormationStack.get_by_stack_name(
                        stack_name, region=region
                    )
                else:
                    stack = updates[stack_name]["stack"]
            except StackNotFound:
                # The Route53 record doesn't have an associated stack
                # fallback to the old logic
                record = None
                for r in Route53.get_records(name=dns_name):
                    if r.set_identifier == stack_name:
                        record = r
                        break
                if percentage:
                    record.weight = percentage
                    hosted_zone.upsert(
                        [record],
                        comment="Change weight of {} to {}".format(
                            stack_name, percentage
                        ),
                    )
                else:
                    hosted_zone.delete(
                        [record],
                        comment="Delete {} "
                        "because traffic for it is 0".format(stack_name),
                    )
                changed = True
                continue

            for key, resource in stack.template["Resources"].items():
                if (
                    resource["Type"] == ResourceType.route53_record_set
                    and resource["Properties"]["Name"] == dns_name
                ):
                    dns_record = stack.template["Resources"][key]
                    break

            try:
                dns_record["Properties"]["Weight"] = percentage
            except NameError:
                raise ELBNotFound(dns_name)

            if stack_name not in updates.keys():
                update = {"stack": stack, "zones": {}}
                updates[stack_name] = update
            else:
                update = updates[stack_name]

            if domain not in update["zones"].keys():
                records = list()
                update["zones"][domain] = records
            else:
                records = update["zones"][domain]
            record = None
            for r in Route53.get_records(name=dns_name):
                if r.set_identifier == stack_name:
                    record = r
                    break
            if record and record.weight != percentage:
                record.weight = percentage
                records.append(
                    {
                        "record": record,
                        "comment": "Change weight of {} to {}".format(
                            stack_name, percentage
                        ),
                    }
                )

    for key, update in updates.items():
        try:
            update["stack"].update()
        except StackNotUpdated:
            # make sure we update DNS records which were not updated via CloudFormation
            for domain, records in update["zones"].items():
                hosted_zone = Route53HostedZone.get_by_domain_name(domain)
                for zone_update in records:
                    hosted_zone.upsert(
                        [zone_update["record"]], comment=zone_update["comment"]
                    )
                    changed = True
        else:
            changed = True

    if changed:
        ok()
    else:
        ok(" not changed")


def dump_traffic_changes(
    stack_name: str,
    identifier: str,
    identifier_versions: {str: str},
    known_record_weights: {str: int},
    new_record_weights: {str: int},
    compensations: {str: int},
    deltas: {str: int},
):
    """
    dump changes to the traffic settings for the given versions
    """
    rows = [
        {
            "stack_name": stack_name,
            "version": identifier_versions.get(i),
            "identifier": i,
            "old_weight%": known_record_weights.get(i),
            # 'delta': (delta if new_record_weights[i] else 0 if i != identifier else forced_delta),
            "delta": deltas[i],
            "compensation": compensations.get(i),
            "new_weight%": new_record_weights.get(i),
        }
        for i in known_record_weights.keys()
    ]

    full_switch = max(new_record_weights.values()) == FULL_PERCENTAGE

    for r in rows:
        d = r["delta"]
        c = r["compensation"]
        if full_switch and not d and c:
            d = -c
        r["delta"] = (d / PERCENT_RESOLUTION) if d else None
        r["old_weight%"] /= PERCENT_RESOLUTION
        r["new_weight%"] /= PERCENT_RESOLUTION
        r["compensation"] = (c / PERCENT_RESOLUTION) if c else None
        if identifier == r["identifier"]:
            r["current"] = "<"

    return sorted(rows, key=lambda x: identifier_versions.get(x["identifier"], ""))


def print_traffic_changes(message: list):
    print_table(
        [
            "stack_name",
            "version",
            "identifier",
            "old_weight%",
            "delta",
            "compensation",
            "new_weight%",
            "current",
        ],
        message,
    )


class StackVersion(
    collections.namedtuple(
        "StackVersion", "name version domain lb_dns_name notification_arns"
    )
):
    @property
    def identifier(self):
        return "{}-{}".format(self.name, self.version)

    @property
    def dns_name(self):
        return ["{}.".format(x) for x in self.domain]


def get_stack_versions(stack_name: str, region: str) -> Iterator[StackVersion]:
    """Get stack versions by name and region."""
    cf = boto3.resource("cloudformation", region)
    for stack in get_stacks([StackReference(name=stack_name, version=None)], region):
        if stack.StackStatus in ("ROLLBACK_COMPLETE", "CREATE_FAILED"):
            continue
        details = cf.Stack(stack.StackId)
        lb_dns_name = []
        domain = []
        notification_arns = details.notification_arns
        for res in details.resource_summaries.all():
            if res.resource_type == "AWS::ElasticLoadBalancing::LoadBalancer":
                elb = BotoClientProxy("elb", region)
                try:
                    lbs = elb.describe_load_balancers(
                        LoadBalancerNames=[res.physical_resource_id]
                    )
                except ClientError as e:
                    error_code = extract_client_error_code(e)
                    if error_code == "LoadBalancerNotFound":
                        continue
                lb_dns_name.append(lbs["LoadBalancerDescriptions"][0]["DNSName"])
            elif res.resource_type == "AWS::Route53::RecordSet":
                if "version" not in res.logical_id.lower():
                    domain.append(res.physical_resource_id)
        yield StackVersion(
            stack_name,
            get_tag(details.tags, "StackVersion"),
            domain,
            lb_dns_name,
            notification_arns,
        )


def get_version(versions: list, version: str):
    for ver in versions:
        if ver.version == version:
            return ver
    raise click.UsageError("Stack version {} not found".format(version))


def get_records(domain: str):
    domain = "{}.".format(domain.rstrip("."))
    if DNS_RR_CACHE.get(domain) is None:
        hosted_zone = Route53HostedZone.get_by_domain_name(domain)
        route53 = BotoClientProxy("route53")
        result = route53.list_resource_record_sets(HostedZoneId=hosted_zone.id)
        records = result["ResourceRecordSets"]
        while result["IsTruncated"]:
            recordfilter = {
                "HostedZoneId": hosted_zone.id,
                "StartRecordName": result["NextRecordName"],
                "StartRecordType": result["NextRecordType"],
            }
            if result.get("NextRecordIdentifier"):
                recordfilter["StartRecordIdentifier"] = result.get(
                    "NextRecordIdentifier"
                )

            result = route53.list_resource_record_sets(**recordfilter)
            records.extend(result["ResourceRecordSets"])
        DNS_RR_CACHE[domain] = records
    return DNS_RR_CACHE[domain]


def print_version_traffic(stack_ref: StackReference, region):
    versions = list(get_stack_versions(stack_ref.name, region))
    identifier_versions = collections.OrderedDict(
        (version.identifier, version.version) for version in versions
    )
    if stack_ref.version:
        version = get_version(versions, stack_ref.version)
    elif versions:
        version = versions[0]
    else:
        raise click.UsageError('No stack version of "{}" found'.format(stack_ref.name))

    if not version.domain:
        raise click.UsageError(
            "Stack {} version {} has " "no domain".format(version.name, version.version)
        )

    known_record_weights, _, _ = get_weights(
        version.dns_name, version.identifier, identifier_versions.keys()
    )

    rows = [
        {
            "stack_name": version.name,
            "version": identifier_versions.get(i),
            "identifier": i,
            "weight%": known_record_weights[i],
        }
        for i in known_record_weights.keys()
    ]

    for r in rows:
        r["weight%"] /= PERCENT_RESOLUTION
        if version.identifier == r["identifier"]:
            r["current"] = "<"

    cols = "stack_name version identifier weight%".split()
    if stack_ref.version:
        cols.append("current")
    print_table(
        cols, sorted(rows, key=lambda x: identifier_versions.get(x["identifier"], ""))
    )


def change_version_traffic(stack_ref: StackReference, percentage: float, region: str):
    versions = list(get_stack_versions(stack_ref.name, region))
    arns = []
    for each_version in versions:
        arns = arns + each_version.notification_arns
    identifier_versions = collections.OrderedDict(
        (version.identifier, version.version) for version in versions
    )
    version = get_version(versions, stack_ref.version)

    identifier = version.identifier

    if not version.domain:
        raise click.UsageError(
            "Stack {} version {} has " "no domain".format(version.name, version.version)
        )

    percentage = int(percentage * PERCENT_RESOLUTION)
    known_record_weights, partial_count, partial_sum = get_weights(
        version.dns_name, identifier, identifier_versions.keys()
    )

    if partial_count == 0 and percentage == 0:
        # disable the last remaining version
        new_record_weights = {i: 0 for i in known_record_weights.keys()}
        message = 'DNS record "{dns_name}" will be removed from that ' "stack".format(
            dns_name=version.dns_name
        )
        ok(msg=message)
    else:
        with Action("Calculating new weights.."):
            compensations = {}
            if partial_count:
                delta = int(
                    (FULL_PERCENTAGE - percentage - partial_sum) / partial_count
                )
            else:
                delta = 0
                if percentage > 0:
                    # will put the only last version to full traffic percentage
                    compensations[identifier] = FULL_PERCENTAGE - percentage
                    percentage = int(FULL_PERCENTAGE)
            new_record_weights, deltas = calculate_new_weights(
                delta, identifier, known_record_weights, percentage
            )
            total_weight = sum(new_record_weights.values())
            calculation_error = FULL_PERCENTAGE - total_weight
            if calculation_error and calculation_error < FULL_PERCENTAGE:
                compensate(
                    calculation_error,
                    compensations,
                    identifier,
                    new_record_weights,
                    partial_count,
                    percentage,
                    identifier_versions,
                )
            assert sum(new_record_weights.values()) == FULL_PERCENTAGE
        message = dump_traffic_changes(
            stack_ref.name,
            identifier,
            identifier_versions,
            known_record_weights,
            new_record_weights,
            compensations,
            deltas,
        )
        print_traffic_changes(message)
        inform_sns(arns, message, region)
    set_new_weights(version.dns_name, known_record_weights, new_record_weights, region)


def inform_sns(arns: list, message: str, region):
    jsonizer = JSONEncoder()
    sns_topics = set(arns)
    sns = BotoClientProxy("sns", region_name=region)
    for sns_topic in sns_topics:
        sns.publish(
            TopicArn=sns_topic,
            Subject="SenzaTrafficRedirect",
            Message=jsonizer.encode(message),
        )


def resolve_to_ip_addresses(dns_name: str) -> set:
    """
    Try to resolve the given DNS name to IPv4 addresses and return empty set on ANY error.
    """
    try:
        answers = dns.resolver.query(dns_name, "A")
    except Exception:
        return set()
    else:
        return {answer.address for answer in answers}
