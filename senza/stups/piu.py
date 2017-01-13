from subprocess import call
from typing import Optional

from ..exceptions import PiuNotFound
from ..manaus.route53 import Route53, Route53Record  # NOQA pylint: disable=locally-disabled, unused-import


class Piu:
    """
    Wrapper around `piu <https://github.com/zalando-stups/piu>`_

    For more information about `piu` see
    http://stups.readthedocs.io/en/latest/user-guide/ssh-access.html#ssh-access
    """
    @staticmethod
    def request_access(instance: str, reason: str, odd_host: Optional[str],
                       connect: bool):
        """
        Request SSH access to a single host
        """
        reason = '{} via senza'.format(reason)
        cmd = ['piu', 'request-access',
               instance, reason]

        if connect:
            cmd.append('--connect')

        if odd_host is not None:
            cmd.extend(['-O', odd_host])

        try:
            call(cmd)
        except FileNotFoundError:
            raise PiuNotFound

    @staticmethod
    def find_odd_host(region: str) -> Optional[str]:
        """
        Tries to find the odd host based on the region and route53 records
        """
        route53 = Route53()
        hosted_zones = list(route53.get_hosted_zones())
        for hosted_zone in hosted_zones:
            potential_name = 'odd-{region}.{domain}'.format(region=region,
                                                            domain=hosted_zone.name)
            records = route53.get_records(name=potential_name)
            try:
                record = next(records)  # type: Route53Record
            except StopIteration:
                # The domain name was not found
                pass
            else:
                odd_host = record.name[:-1]  # remove the trailing dot
                return odd_host

        return None
