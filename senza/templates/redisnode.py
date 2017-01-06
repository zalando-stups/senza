"""
Elasticache node running redis, without replication / HA (for caching)
"""

from clickclick import warning
from senza.utils import pystache_render

from ._helper import prompt, check_security_group, check_value


TEMPLATE = '''
# basic information for generating and executing this definition
SenzaInfo:
  StackName: {{ application_id }}

# a list of senza components to apply to the definition
SenzaComponents:

  # this basic configuraation is required for the other components
  - Configuration:
      Type: Senza::StupsAutoConfiguration # auto-detect network setup

  - {{ application_id }}:
      Type: Senza::RedisNode
      CacheNodeType: {{ instance_type }}
      SecurityGroups:
        - redis-{{ application_id }}
'''


def gather_user_variables(variables, region, account_info):  # pylint: disable=locally-disabled, unused-argument
    """
    Gather all the variables needed to create the redis node
    """
    # maximal 32 characters because of the loadbalancer-name
    prompt(variables, 'application_id', 'Application ID', default='hello-world',
           value_proc=check_value(18, '^[a-zA-Z][-a-zA-Z0-9]*$'))
    prompt(variables, 'instance_type', 'EC2 instance type', default='cache.t2.small')

    sg_name = 'redis-{}'.format(variables['application_id'])

    rules_missing = check_security_group(sg_name, [('tcp', 6379)], region, allow_from_self=True)
    if ('tcp', 6379) in rules_missing:
        warning('Security group {} does not allow tcp/6379 access, '
                'you will not be able to access your redis'.format(sg_name))

    return variables


def generate_definition(variables):
    """
    Generates the redis node definition yaml from template
    """
    definition_yaml = pystache_render(TEMPLATE, variables)
    return definition_yaml
