
import boto.route53

from senza.components.elastic_load_balancer import component_elastic_load_balancer


def get_default_zone(region):
    dns_conn = boto.route53.connect_to_region(region)
    zones = dns_conn.get_zones()
    domains = sorted([zone.name.rstrip('.') for zone in zones])
    if not domains:
        raise Exception('No Route53 hosted zone found')
    return domains[0]


def component_weighted_dns_elastic_load_balancer(definition, configuration, args, info, force):
    if 'Domains' not in configuration:

        if 'MainDomain' in configuration:
            main_domain = configuration['MainDomain']
            main_subdomain, main_zone = main_domain.split('.', 1)
            del configuration['MainDomain']
        else:
            main_zone = get_default_zone(args.region)
            main_subdomain = info['StackName']

        if 'VersionDomain' in configuration:
            version_domain = configuration['VersionDomain']
            version_subdomain, version_zone = version_domain.split('.', 1)
            del configuration['VersionDomain']
        else:
            version_zone = get_default_zone(args.region)
            version_subdomain = '{}-{}'.format(info['StackName'], info['StackVersion'])

        configuration['Domains'] = {'MainDomain': {'Type': 'weighted',
                                                   'Zone': main_zone,
                                                   'Subdomain': main_subdomain},
                                    'VersionDomain': {'Type': 'standalone',
                                                      'Zone': version_zone,
                                                      'Subdomain': version_subdomain}}
    return component_elastic_load_balancer(definition, configuration, args, info, force)
