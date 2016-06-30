from ..manaus.route53 import Route53


class Piu:
    @classmethod
    def find_odd_host(cls, region: str) -> str:
        route53 = Route53()
        hosted_zones = list(route53.get_hosted_zones())
        # TODO try all the hosted zones and see if the domain exists
        hosted_zone = hosted_zones.pop()
        domain_name = hosted_zone.name[:-1]
        return 'odd-{region}.{domain}'.format(region=region,
                                              domain=domain_name)
