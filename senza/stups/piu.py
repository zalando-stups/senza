from typing import Optional

from subprocess import run
from ..manaus.route53 import Route53, Route53Record  # NOQA


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
    def find_odd_host(region: str) -> Optional[str]:
        route53 = Route53()
        hosted_zones = list(route53.get_hosted_zones())
        for hosted_zone in hosted_zones:
            potential_name = 'odd-{region}.{domain}'.format(region=region,
                                                            domain=hosted_zone.name)
            records = route53.get_records(name=potential_name)
            try:
                record = next(records)  # type: Route53Record
            except StopIteration:
                pass
            else:
                odd_host = record.name[:-1]  # remove the trailing dot
                return odd_host

        return None
