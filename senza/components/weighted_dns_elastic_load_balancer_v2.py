
from senza.components.weighted_dns_elastic_load_balancer import component_weighted_dns_elastic_load_balancer
from senza.components.elastic_load_balancer_v2 import component_elastic_load_balancer_v2


def component_weighted_dns_elastic_load_balancer_v2(definition, configuration, args, info, force, account_info):
    return component_weighted_dns_elastic_load_balancer(definition, configuration, args, info, force, account_info,
                                                        lb_component=component_elastic_load_balancer_v2)
