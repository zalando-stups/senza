from typing import Optional

from subprocess import run
from ..manaus.route53 import Route53

class Piu:
    @staticmethod
    def request_access(instance: str, reason: str, odd_host: Optional[str]):
        """
        Request SSH access to a single host
        """
        reason = '{} via senza'.format(reason)
        cmd = ['piu', 'request-access',
               instance, reason]
        if odd_host is not None:
            cmd.extend(['-O', odd_host])
        run(cmd)

    @staticmethod
    def find_odd_host(region: str) -> str:
        route53 = Route53()
        hosted_zones = list(route53.get_hosted_zones())
        # TODO try all the hosted zones and see if the domain exists
        hosted_zone = hosted_zones.pop()
        domain_name = hosted_zone.name[:-1]
        return 'odd-{region}.{domain}'.format(region=region,
                                              domain=domain_name)
