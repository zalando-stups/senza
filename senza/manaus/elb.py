from typing import Optional

from .constants import ELB_REGION_HOSTED_ZONE
from .route53 import Route53HostedZone, Route53


# see http://docs.aws.amazon.com/general/latest/gr/rande.html#elb_region

class ELB:
    @staticmethod
    def get_hosted_zone_for(*,
                            dns_name: Optional[str]=None,
                            region: Optional[str]=None) -> Route53HostedZone:

        if all([dns_name, region]):
            raise ValueError("Provide only one of dns_name and region.")

        if dns_name is not None:
            # dns_name = app-name.REGION.elb.amazonaws.com
            _, region, _ = dns_name.split('.', maxsplit=2)

        # TODO get hosted zone by id
        hosted_zone_id = ELB_REGION_HOSTED_ZONE[region]
        hosted_zone = next(Route53.get_hosted_zones(id=hosted_zone_id))
        return hosted_zone
