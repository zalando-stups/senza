
from senza.components.elastic_load_balancer import component_elastic_load_balancer


def component_weighted_dns_elastic_load_balancer(definition, configuration, args, info, force, account_info,
                                                 lb_component=component_elastic_load_balancer):
    if 'Domains' not in configuration:
        if 'MainDomain' in configuration:
            main_domain = configuration['MainDomain']
            main_subdomain, main_zone = account_info.split_domain(main_domain)
            del configuration['MainDomain']
        else:
            main_zone = account_info.Domain
            main_subdomain = info['StackName']

        if 'VersionDomain' in configuration:
            version_domain = configuration['VersionDomain']
            version_subdomain, version_zone = account_info.split_domain(version_domain)
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
    return lb_component(definition, configuration, args, info, force, account_info)
