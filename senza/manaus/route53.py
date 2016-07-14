from typing import Iterator, List, Dict, Any, Optional, Union

import boto3


class Route53HostedZone:
    """
    See:
    http://boto3.readthedocs.io/en/latest/reference/services/route53.html#Route53.Client.list_hosted_zones
    """

    def __init__(self,
                 id: str,
                 name: str,
                 caller_reference: str,
                 config: Dict[str, Any],
                 resource_record_set_count: int):
        self.id = id
        self.name = name
        self.caller_reference = caller_reference
        self.config = config
        self.resource_record_set_count = resource_record_set_count

        # extra properties
        self.domain_name = name.rstrip('.')

    def __repr__(self):
        return '<Route53HostedZone: {name}>'.format_map(vars(self))

    @classmethod
    def from_boto_dict(cls, hosted_zone_dict: Dict[str, Any]) -> 'Route53HostedZone':
        id = hosted_zone_dict['Id']
        name = hosted_zone_dict['Name']
        caller_reference = hosted_zone_dict['CallerReference']
        config = hosted_zone_dict['Config']
        resource_record_set_count = hosted_zone_dict['ResourceRecordSetCount']

        return cls(id, name, caller_reference, config,
                   resource_record_set_count)


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
                 weight: Optional[int]=None):

        self.name = name
        self.type = type

        self.ttl = ttl
        self.resource_records = resource_records
        self.alias_target = alias_target  # Alias resource record sets only
        self.failover = failover  # Failover resource record sets only
        self.geo_location = geo_location  # Geo location resource record sets only
        self.health_check_id = health_check_id  # Health Check resource record sets only
        self.region = region  # Latency-based resource record sets only
        self.set_identifier = set_identifier  # Weighted, Latency, Geo, and Failover resource record sets only
        self.traffic_policy_instance_id = traffic_policy_instance_id
        self.weight = weight  # Weighted resource record sets only

    @property
    def boto_dict(self):
        """
        Generates the dict to change records set

        See:
         http://boto3.readthedocs.io/en/latest/reference/services/route53.html#Route53.Client.change_resource_record_sets
        """
        # TODO Route53.change method
        boto_dict = {"Name": self.name,
                     "Type": self.type}

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

    def __repr__(self):
        return '<Route53Record: {name}>'.format_map(vars(self))

    @classmethod
    def from_boto_dict(cls, record_dict: Dict[str, Any]) -> 'Route53Record':
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
        weight = record_dict.get('weight')

        return cls(name, type, ttl, resource_records,
                   alias_target, failover, geo_location, health_check_id,
                   region, set_identifier, traffic_policy_instance_id, weight)


class Route53:

    def __init__(self):
        self.client = boto3.client('route53')

    @staticmethod
    def get_hosted_zones(domain_name: Optional[str]=None) -> Iterator[Route53HostedZone]:
        """
        Gets hosted zones from Route53. If a ``domain_name`` is provided
        only hosted zones that match the domain name will be yielded
        """

        if domain_name is not None:
            domain_name = '{}.'.format(domain_name.rstrip('.'))

        client = boto3.client('route53')
        result = client.list_hosted_zones()
        hosted_zones = result["HostedZones"]
        while result.get('IsTruncated', False):
            recordfilter = {'Marker': result['NextMarker']}
            result = client.list_hosted_zones(**recordfilter)
            hosted_zones.extend(result['HostedZones'])

        for zone in hosted_zones:
            hosted_zone = Route53HostedZone.from_boto_dict(zone)
            if domain_name is None or domain_name.endswith(hosted_zone.name):
                yield hosted_zone

    @classmethod
    def get_records(cls, *,
                    name: Optional[str]=None) -> Iterator[Route53Record]:
        client = boto3.client('route53')
        if name is not None and not name.endswith('.'):
            name += '.'
        for zone in cls.get_hosted_zones():
            # TODO use paginator
            response = client.list_resource_record_sets(HostedZoneId=zone.id)
            resources = response["ResourceRecordSets"]  # type: List[Dict[str, Any]]
            for resource in resources:
                record = Route53Record.from_boto_dict(resource)
                if name is not None and record.name != name:
                    continue
                yield record


# TODO method to convert cname to alias

#             {'AliasTarget': {
#                 'DNSName': 'hello-bus-v49testsenza-1456711526.eu-central-1.elb.amazonaws.com.',
#                 'EvaluateTargetHealth': False,
#                 'HostedZoneId': 'Z215JYRZR1TBD5'},
#              'Name': 'hello-bus-v49testsenza-test.bus.zalan.do.',
#              'Type': 'A'},
#
#
# {'Name': 'hello-bus-v50.bus.zalan.do.',
#  'ResourceRecords': [
#      {'Value': 'hello-bus-v50-1586593886.eu-central-1.elb.amazonaws.com'}],
#  'TTL': 20,
#  'Type': 'CNAME'},

# for each cloud formation stack:
# domains = [resource for resource in resources if resource['Name'].startswith(app+'.') and resource['Type'] == 'CNAME']
# new = AliasTarget
