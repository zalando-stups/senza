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

        def __repr__(self):
            return '<Route53HostedZone: {name}>'.format_map(vars(self))

        return cls(id, name, caller_reference, config,
                   resource_record_set_count)


class Route53Record:
    """
    See:
    http://boto3.readthedocs.io/en/latest/reference/services/route53.html#Route53.Client.list_resource_record_sets
    """

    def __init__(self,
                 name: str,
                 resource_records: List[Dict[str, str]],
                 ttl: int,
                 type: str,
                 alias_target: Optional[Dict[str, Union[str, bool]]]=None,
                 failover: Optional[str]=None,
                 geo_location: Optional[Dict[str, str]]=None,
                 health_check_id: Optional[int]=None,
                 region: Optional[str]=None,
                 set_identifier: Optional[str]=None,
                 traffic_policy_instance_id: Optional[str]=None,
                 weight: Optional[int]=None):
        self.name = name
        self.resource_records = resource_records
        self.ttl = ttl
        self.type = type

        # Optional
        self.alias_target = alias_target  # Alias resource record sets only
        self.failover = failover  # Failover resource record sets only
        self.geo_location = geo_location  # Geo location resource record sets only
        self.health_check_id = health_check_id  # Health Check resource record sets only
        self.region = region  # Latency-based resource record sets only
        self.set_identifier = set_identifier  # Weighted, Latency, Geo, and Failover resource record sets only
        self.traffic_policy_instance_id = traffic_policy_instance_id
        self.weight = weight  # Weighted resource record sets only

    def __repr__(self):
        return '<Route53Record: {name}>'.format_map(vars(self))

    @classmethod
    def from_boto_dict(cls, record_dict: Dict[str, Any]) -> 'Route53Record':
        """
        Returns a Route53Record based on the dict returned by boto3
        """
        name = record_dict['Name']
        resource_records = record_dict['ResourceRecords']
        ttl = record_dict['TTL']
        type = record_dict['Type']

        alias_target = record_dict.get('AliasTarget')
        failover = record_dict.get('Failover')
        geo_location = record_dict.get('GeoLocation')
        health_check_id = record_dict.get('HealthCheckId')
        region = record_dict.get('Region')
        set_identifier = record_dict.get('SetIdentifier')
        traffic_policy_instance_id = record_dict.get('TrafficPolicyInstanceId')
        weight = record_dict.get('weight')

        return cls(name, resource_records, ttl, type,
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

    def get_records(self, *,
                    name: Optional[str]=None) -> Iterator[Route53Record]:
        for zone in self.get_hosted_zones():
            # TODO use paginator
            response = self.client.list_resource_record_sets(HostedZoneId=zone.id)
            resources = response["ResourceRecordSets"]  # type: List[Dict[str, Any]]
            for resource in resources:
                record = Route53Record.from_boto_dict(resource)
                if name is not None and record.name != name:
                    continue
                yield record
