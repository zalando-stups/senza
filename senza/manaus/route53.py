import sys
from collections import defaultdict
from copy import deepcopy
from enum import Enum
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple, Union

from click import confirm

from .boto_proxy import BotoClientProxy
from .exceptions import (ELBNotFound, HostedZoneNotFound, InvalidState,
                         RecordNotFound)


class ChangeAction(str, Enum):
    """
    DNS record type
    """

    CREATE = 'CREATE'
    DELETE = 'DELETE'
    UPSERT = 'UPSERT'


class RecordType(str, Enum):
    """
    DNS record type
    """
    A = 'A'
    AAAA = 'AAAA'
    CNAME = 'CNAME'
    MX = 'MX'
    NS = 'NS'
    PRT = 'PRT'
    SOA = 'SOA'
    SPF = 'SPF'
    SRV = 'SRV'
    TXT = 'TXT'


class Route53HostedZone:
    """
    See:
    http://boto3.readthedocs.io/en/latest/reference/services/route53.html#Route53.Client.list_hosted_zones
    """

    def __init__(self,
                 id: str,
                 name: Optional[str]=None,
                 caller_reference: Optional[str]=None,
                 config: Optional[Dict[str, Any]]=None,
                 resource_record_set_count: Optional[int]=None):
        self.id = id
        self.name = name
        self.caller_reference = caller_reference
        self.config = config
        self.resource_record_set_count = resource_record_set_count

        # extra properties
        self.domain_name = name.rstrip('.') if name else None

    def __repr__(self):
        identifier = self.name or self.id
        return '<Route53HostedZone: {name}>'.format(name=identifier)

    @classmethod
    def get_by_domain_name(cls, domain_name: str) -> 'Route53HostedZone':
        hosted_zone_iter = Route53.get_hosted_zones(domain_name=domain_name)
        try:
            hosted_zone = next(hosted_zone_iter)
        except StopIteration:
            raise HostedZoneNotFound(domain_name)
        return hosted_zone

    @classmethod
    def get_by_id(cls, id: str) -> 'Route53HostedZone':
        hosted_zone_iter = Route53.get_hosted_zones(id=id)
        try:
            hosted_zone = next(hosted_zone_iter)
        except StopIteration:
            raise HostedZoneNotFound(id)
        return hosted_zone

    @classmethod
    def from_boto_dict(cls, hosted_zone_dict: Dict[str, Any]) -> 'Route53HostedZone':
        id = hosted_zone_dict['Id']
        name = hosted_zone_dict['Name']
        caller_reference = hosted_zone_dict['CallerReference']
        config = hosted_zone_dict['Config']
        resource_record_set_count = hosted_zone_dict['ResourceRecordSetCount']

        return cls(id, name, caller_reference, config,
                   resource_record_set_count)

    def change(self,
               changes: Iterable[Tuple[str, "Route53Record"]],
               comment: Optional[str]=None) -> Dict[str, Any]:
        """
        Submits changes to Route53. Returns the dict sent to
        AWS.

        See:
        http://boto3.readthedocs.io/en/latest/reference/services/route53.html#Route53.Client.change_resource_record_sets
        """

        client = BotoClientProxy('route53')

        change_batch = {'Changes': []}
        if comment is not None:
            change_batch['Comment'] = comment
        for action, record in changes:
            change = {'Action': action.upper(),
                      'ResourceRecordSet': record.boto_dict}
            change_batch['Changes'].append(change)

        if change_batch['Changes']:
            client.change_resource_record_sets(HostedZoneId=self.id,
                                               ChangeBatch=change_batch)

        return change_batch

    def create(self,
               changed_records: Iterable["Route53Record"],
               comment: Optional[str]=None) -> Dict[str, Any]:
        """
        Submits changes to be created in Route53. Returns the dict sent to
        AWS.

        See:
        http://boto3.readthedocs.io/en/latest/reference/services/route53.html#Route53.Client.change_resource_record_sets
        """

        changes = [(ChangeAction.CREATE, record) for record in changed_records]

        return self.change(changes, comment)

    def delete(self,
               changed_records: Iterable["Route53Record"],
               comment: Optional[str]=None) -> Dict[str, Any]:
        """
        Submits changes to be deleted in Route53. Returns the dict sent to
        AWS.

        See:
        http://boto3.readthedocs.io/en/latest/reference/services/route53.html#Route53.Client.change_resource_record_sets
        """

        changes = [(ChangeAction.DELETE, record) for record in changed_records]

        return self.change(changes, comment)

    def upsert(self,
               changed_records: Iterable["Route53Record"],
               comment: Optional[str]=None) -> Dict[str, Any]:
        """
        Submits changes to be upsterted in Route53. Returns the dict sent to
        AWS.

        See:
        http://boto3.readthedocs.io/en/latest/reference/services/route53.html#Route53.Client.change_resource_record_sets
        """

        changes = [(ChangeAction.UPSERT, record) for record in changed_records]

        return self.change(changes, comment)


class Route53Record:
    """
    See:
    http://boto3.readthedocs.io/en/latest/reference/services/route53.html#Route53.Client.list_resource_record_sets
    """

    def __init__(self,
                 name: str,
                 type: str,
                 ttl: Optional[int]=None,
                 resource_records: Optional[List[Dict[str, str]]]=None,
                 alias_target: Optional[Dict[str, Union[str, bool]]]=None,
                 failover: Optional[str]=None,
                 geo_location: Optional[Dict[str, str]]=None,
                 health_check_id: Optional[int]=None,
                 region: Optional[str]=None,
                 set_identifier: Optional[str]=None,
                 traffic_policy_instance_id: Optional[str]=None,
                 weight: Optional[int]=None,
                 hosted_zone: Optional["Route53HostedZone"]=None):

        self.name = name
        self.type = RecordType[type.upper()]

        self.ttl = ttl
        self.resource_records = resource_records
        self.alias_target = alias_target  # Alias resource record sets only
        self.failover = failover  # Failover resource record sets only
        self.geo_location = geo_location  # Geo location resource record sets only
        self.health_check_id = health_check_id  # Health Check resource record sets only
        self.region = region  # Latency-based resource record sets only
        # Weighted, Latency, Geo, and Failover resource record sets only
        self.set_identifier = set_identifier
        self.traffic_policy_instance_id = traffic_policy_instance_id
        self.weight = weight  # Weighted resource record sets only

        self.hosted_zone = hosted_zone

    def __repr__(self):
        return '<Route53Record: {name}>'.format_map(vars(self))

    @classmethod
    def get_by_domain_name(cls, domain_name: str) -> "Route53Record":
        records_iter = Route53.get_records(name=domain_name)
        try:
            record = next(records_iter)
        except StopIteration:
            raise RecordNotFound(domain_name)
        return record

    @property
    def boto_dict(self):
        """
        Generates the dict to change records set

        See:
         http://boto3.readthedocs.io/en/latest/reference/services/route53.html#Route53.Client.change_resource_record_sets
        """

        boto_dict = {"Name": self.name,
                     "Type": self.type.value}

        optional_parameters = [('SetIdentifier', self.set_identifier),
                               ('Weight', self.weight),
                               ('Region', self.region),
                               ('GeoLocation', self.geo_location),
                               ('Failover', self.failover),
                               ('TTL', self.ttl),
                               ('ResourceRecords', self.resource_records),
                               ('AliasTarget', self.alias_target)]

        for key, value in optional_parameters:
            if value is not None:
                boto_dict[key] = value

        return boto_dict

    @classmethod
    def from_boto_dict(cls,
                       record_dict: Dict[str, Any],
                       hosted_zone: Optional["Route53HostedZone"]=None) -> 'Route53Record':
        """
        Returns a Route53Record based on the dict returned by boto3
        """
        name = record_dict['Name']
        type = record_dict['Type']

        ttl = record_dict.get('TTL')
        resource_records = record_dict.get('ResourceRecords')
        alias_target = record_dict.get('AliasTarget')
        failover = record_dict.get('Failover')
        geo_location = record_dict.get('GeoLocation')
        health_check_id = record_dict.get('HealthCheckId')
        region = record_dict.get('Region')
        set_identifier = record_dict.get('SetIdentifier')
        traffic_policy_instance_id = record_dict.get('TrafficPolicyInstanceId')
        weight = record_dict.get('Weight')

        return cls(name, type, ttl, resource_records,
                   alias_target, failover, geo_location, health_check_id,
                   region, set_identifier, traffic_policy_instance_id, weight,
                   hosted_zone=hosted_zone)

    def to_alias(self,
                 target_type: RecordType=RecordType.A) -> "Route53Record":
        """
        Converts record to an Alias record.

        By default it converts the record to an A type Alias but this can
        be overridden by provident a `target_type`.
        """

        # this needs to be imported locally to avoid circular imports
        from .elb import ELB

        if self.alias_target is not None:
            # Record is already an Alias
            return deepcopy(self)
        if self.type == RecordType.CNAME:
            dns_name = self.resource_records[0]['Value']
            # dns name looks like lb-name-123456.aws-region-1.elb.amazonaws.com
            sub_domain, _ = dns_name.split('.', maxsplit=1)  # type: str
            lb_name, _ = sub_domain.rsplit('-', maxsplit=1)

            if dns_name.endswith(".elb.amazonaws.com"):
                elb = ELB.get_by_dns_name(dns_name)
                hosted_zone_id = elb.hosted_zone.id
            else:
                _, hosted_zone_id = self.hosted_zone.id.rsplit('/', maxsplit=1)

            alias_target = {"HostedZoneId": hosted_zone_id,
                            "DNSName": dns_name,
                            "EvaluateTargetHealth": False}
            return self.__class__(name=self.name,
                                  type=target_type,
                                  alias_target=alias_target,
                                  traffic_policy_instance_id=self.traffic_policy_instance_id,
                                  set_identifier=self.set_identifier,
                                  weight=self.weight)
        else:
            raise NotImplementedError("Conversion of {} records to Alias is "
                                      "still not implemented".format(self.type))


class Route53:

    def __init__(self):
        self.client = BotoClientProxy('route53')

    @staticmethod
    def get_hosted_zones(domain_name: Optional[str]=None,
                         id: Optional[str]=None) -> Iterator[Route53HostedZone]:
        """
        Gets hosted zones from Route53. If a ``domain_name`` is provided
        only hosted zones that match the domain name will be yielded
        """

        if domain_name is not None:
            domain_name = '{}.'.format(domain_name.rstrip('.'))

        client = BotoClientProxy('route53')
        result = client.list_hosted_zones()
        hosted_zones = result["HostedZones"]
        while result.get('IsTruncated', False):
            recordfilter = {'Marker': result['NextMarker']}
            result = client.list_hosted_zones(**recordfilter)
            hosted_zones.extend(result['HostedZones'])

        for zone in hosted_zones:
            hosted_zone = Route53HostedZone.from_boto_dict(zone)

            if domain_name and not domain_name.endswith(hosted_zone.name):
                continue

            if id and hosted_zone.id != id:
                continue

            yield hosted_zone

    @classmethod
    def get_records(cls, *,
                    name: Optional[str]=None) -> Iterator[Route53Record]:
        client = BotoClientProxy('route53')
        if name is not None and not name.endswith('.'):
            name += '.'
        for zone in cls.get_hosted_zones():
            response = client.list_resource_record_sets(HostedZoneId=zone.id)
            resources = response["ResourceRecordSets"]  # type: List[Dict[str, Any]]

            # If the response includes more than maxitems resource record sets,
            # the value of the IsTruncated element in the response is true,
            # and the values of the NextRecordName and NextRecordType elements
            # in the response identify the first resource record set in the
            # next group of maxitems resource record sets.
            while response.get('IsTruncated', False):
                next_name = response['NextRecordName']
                next_type = response['NextRecordType']
                response = client.list_resource_record_sets(HostedZoneId=zone.id,
                                                            StartRecordName=next_name,
                                                            StartRecordType=next_type)
                resources.extend(response['ResourceRecordSets'])

            for resource in resources:
                record = Route53Record.from_boto_dict(resource,
                                                      hosted_zone=zone)
                if name is not None and record.name != name:
                    continue
                yield record


def convert_cname_records_to_alias(domain_name: str):
    records = Route53.get_records(name=domain_name)
    converted_records = defaultdict(lambda: {'delete': [],
                                             'upsert': []})
    for record in records:
        if record.type == RecordType.CNAME:
            converted_records[record.hosted_zone]['delete'].append(record)
            try:
                alias_record = record.to_alias()
                converted_records[record.hosted_zone]['upsert'].append(alias_record)
            except ELBNotFound:
                print("Dangling DNS record  will be deleted: {}".format(record.name))

    if converted_records:
        for hosted_zone, records in converted_records.items():
            s = 's' if records != 1 else ''
            interactive_terminal = sys.stdin.isatty()

            msg = ("\n  {name} ({hz}): {n} record{s} need to be converted to "
                   "Alias records".format(name=domain_name,
                                          hz=hosted_zone.name,
                                          n=len(records['upsert']),
                                          s=s))

            # if we are not in an interactive terminal change without asking
            # this is not ideal, but it's needed because of lizzy
            if not interactive_terminal or confirm(msg):
                hosted_zone.delete(records['delete'],
                                   comment="Records that will be converted "
                                           "to Alias")

                print("  Deleted old record{s}".format(s=s))

                hosted_zone.upsert(records['upsert'],
                                   comment="Convert non alias records")
                print("  Inserted alias record{s}".format(s=s))
            else:
                raise InvalidState("Can't change domains because there are "
                                   "non A Type records.")
