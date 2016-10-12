from typing import Dict

from senza.definitions import AccountArguments
from senza.components.elastic_load_balancer import component_elastic_load_balancer
from senza.manaus.route53 import Route53


def component_weighted_dns_elastic_load_balancer(definition,
                                                 configuration: Dict,
                                                 args,
                                                 info,
                                                 force,
                                                 account_info: AccountArguments,
                                                 lb_component=component_elastic_load_balancer):
    if 'Domains' not in configuration:
        if 'MainDomain' in configuration:
            main_domain = configuration['MainDomain']
            main_subdomain, fall_back_hz = account_info.split_domain(main_domain)
            try:
                hosted_zone = next(Route53.get_hosted_zones(domain_name=main_domain))
                main_zone = hosted_zone.name
            except StopIteration:
                main_zone = fall_back_hz
            del configuration['MainDomain']
        else:
            main_zone = account_info.Domain
            main_subdomain = info['StackName']

        if 'VersionDomain' in configuration:
            version_domain = configuration['VersionDomain']
            version_subdomain, fall_back_hz = account_info.split_domain(version_domain)
            try:
                hosted_zone = next(Route53.get_hosted_zones(domain_name=version_domain))
                version_zone = hosted_zone.name
            except StopIteration:
                version_zone = fall_back_hz
            del configuration['VersionDomain']
        else:
            version_zone = account_info.Domain
            version_subdomain = '{}-{}'.format(info['StackName'], info['StackVersion'])

        configuration['Domains'] = {'MainDomain': {'Type': 'weighted',
                                                   'Zone': '{}.'.format(main_zone.rstrip('.')),
                                                   'Subdomain': main_subdomain},
                                    'VersionDomain': {'Type': 'standalone',
                                                      'Zone': '{}.'.format(version_zone.rstrip('.')),
                                                      'Subdomain': version_subdomain}}
    return lb_component(definition, configuration, args, info, force,
                        account_info)
