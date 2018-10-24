"""
ELB_ related classes and functions.

For more information see the `ELB documentation`_ and the `boto3 documentation`_

.. _ELB: https://aws.amazon.com/elasticloadbalancing/
.. _ELB documentation: https://aws.amazon.com/documentation/elastic-load-balancing/
.. _boto3 documentation: http://boto3.readthedocs.io/en/latest/reference/services/elb.html
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from .boto_proxy import BotoClientProxy
from .exceptions import ELBNotFound
from .route53 import Route53HostedZone


class ELBScheme(str, Enum):
    """
    DNS record type
    """

    internet_facing = "internet-facing"
    internal = "internal"

    @classmethod
    def from_str(cls, value: str) -> "ELBScheme":
        """
        Returns the an attribute based on a string as returned by boto
        """
        value = value.replace("-", "_")
        return cls[value]


class ELBHealthCheck:

    """
    Represents the HealthCheck section of an ELB.

    See `HealthCheck` key in:
    http://boto3.readthedocs.io/en/latest/reference/services/elb.html#ElasticLoadBalancing.Client.describe_load_balancers
    """

    def __init__(
        self,
        target: str,
        interval: int,
        timeout: int,
        unhealthy_threshold: int,
        healthy_threshold: int,
    ):
        self.target = target
        self.interval = interval
        self.timeout = timeout
        self.unhealthy_threshold = unhealthy_threshold
        self.healthy_threshold = healthy_threshold

    @classmethod
    def from_boto_dict(cls, health_check: Dict[str, Any]) -> "ELBHealthCheck":
        """
        Instantiates a `ELBHealthCheck` object from the dictionary returned
        by boto3.
        """
        target = health_check["Target"]
        interval = health_check["Interval"]
        timeout = health_check["Timeout"]
        unhealthy_threshold = health_check["UnhealthyThreshold"]
        healthy_threshold = health_check["HealthyThreshold"]

        cls(target, interval, timeout, unhealthy_threshold, healthy_threshold)


class ELBListener:

    """
    Represents the ELBListener section of an ELB.

    See `ELBListener` key in:
    http://boto3.readthedocs.io/en/latest/reference/services/elb.html#ElasticLoadBalancing.Client.describe_load_balancers
    """

    def __init__(
        self,
        protocol: str,
        load_balancer_port: int,
        instance_protocol: str,
        instance_port: int,
        ssl_certificate_id: str,
    ):
        self.protocol = protocol
        self.load_balancer_port = load_balancer_port
        self.instance_protocol = instance_protocol
        self.instance_port = instance_port
        self.ssl_certificate_id = ssl_certificate_id

    @classmethod
    def from_boto_dict(cls, listener) -> "ELBListener":
        """
        Instantiates a `ELBListener` object from the dictionary returned
        by boto3.
        """

        protocol = listener["Protocol"]
        load_balancer_port = listener["LoadBalancerPort"]
        instance_protocol = listener["InstanceProtocol"]
        instance_port = listener["InstancePort"]
        ssl_certificate_id = listener.get("SSLCertificateId")

        return cls(
            protocol,
            load_balancer_port,
            instance_protocol,
            instance_port,
            ssl_certificate_id,
        )


class ELB:

    """
    Elastic Load Balancer.

    See:
    http://boto3.readthedocs.io/en/latest/reference/services/elb.html#ElasticLoadBalancing.Client.describe_load_balancers
    """

    def __init__(
        self,
        name: str,
        dns_name: str,
        hosted_zone_name: str,
        hosted_zone_id: str,
        listener_descriptions: dict,
        policies: dict,
        backend_server_descriptions: list,
        availability_zones: List[str],
        subnets: List[str],
        instance_ids: List[str],
        vpc_id: str,
        health_check: ELBHealthCheck,
        source_security_group: Dict[str, str],
        security_groups: List[str],
        created_time: datetime,
        scheme: ELBScheme,
        listeners: Optional[ELBListener] = None,
        region: Optional[str] = None,
    ):
        self.name = name
        self.dns_name = dns_name
        self.hosted_zone_name = hosted_zone_name
        self.hosted_zone_id = hosted_zone_id
        self.policies = policies
        self.backend_server_descriptions = backend_server_descriptions
        self.availability_zones = availability_zones
        self.subnets = subnets
        self.vpc_id = vpc_id
        self.instance_ids = instance_ids
        self.health_check = health_check
        self.source_security_group = source_security_group
        self.security_groups = security_groups
        self.created_time = created_time
        self.scheme = scheme

        self.hosted_zone = Route53HostedZone(name=hosted_zone_name, id=hosted_zone_id)

        if listeners is None:
            listeners = [
                ELBListener.from_boto_dict(each["Listener"])
                for each in listener_descriptions
            ]
        self.listeners = listeners

        if region is None:
            _, region, _ = dns_name.split(".", maxsplit=2)

        self.region = region

    @classmethod
    def from_boto_dict(cls, load_balancer) -> "ELB":
        """
        Instantiates a `ELB` object from the dictionary returned
        by `boto3.client('elb').describe_load_balancers`.
        """

        name = load_balancer["LoadBalancerName"]
        dns_name = load_balancer["DNSName"]
        hosted_zone_name = load_balancer.get("CanonicalHostedZoneName")
        hosted_zone_id = load_balancer["CanonicalHostedZoneNameID"]
        listener_descriptions = load_balancer["ListenerDescriptions"]
        policies = load_balancer["Policies"]
        backend_server_descriptions = load_balancer["BackendServerDescriptions"]
        availability_zones = load_balancer["AvailabilityZones"]
        subnets = load_balancer["Subnets"]
        vpc_id = load_balancer["VPCId"]
        instance_ids = load_balancer["Instances"]
        health_check = ELBHealthCheck.from_boto_dict(load_balancer["HealthCheck"])
        source_security_group = load_balancer["SourceSecurityGroup"]
        security_groups = load_balancer["SecurityGroups"]
        created_time = load_balancer["CreatedTime"]
        scheme = ELBScheme.from_str(load_balancer["Scheme"])

        return cls(
            name,
            dns_name,
            hosted_zone_name,
            hosted_zone_id,
            listener_descriptions,
            policies,
            backend_server_descriptions,
            availability_zones,
            subnets,
            vpc_id,
            instance_ids,
            health_check,
            source_security_group,
            security_groups,
            created_time,
            scheme,
        )

    @classmethod
    def get_by_dns_name(cls, dns_name: str) -> "ELB":
        """
        Gets a `ELB` by its DNS name and raises and `ELBNotFound` exception
        if such an ELB doesn't exist.

        :raises: ELBNotFound
        """
        _, region, _ = dns_name.split(".", maxsplit=2)
        client = BotoClientProxy("elb", region)

        response = client.describe_load_balancers()
        next_marker = response.get("NextMarker")
        load_balancers = response["LoadBalancerDescriptions"]  # type: List
        while next_marker:
            response = client.describe_load_balancers(Marker=next_marker)
            next_marker = response.get("NextMarker")
            load_balancers.extend(response["LoadBalancerDescriptions"])

        for load_balancer in load_balancers:
            if load_balancer["DNSName"] == dns_name:
                return cls.from_boto_dict(load_balancer)

        raise ELBNotFound(dns_name)
