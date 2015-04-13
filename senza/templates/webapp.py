'''
HTTP app with auto scaling, ELB and DNS
'''

import click
import pystache
import yaml

TEMPLATE = '''
# basic information for generating and executing this definition
SenzaInfo:
  StackName: {{application_id}}
  Parameters:
    - ImageVersion:
        Description: "Docker image version of {{ application_id }}."

# a list of senza components to apply to the definition
SenzaComponents:

  # this basic configuration is required for the other components
  - Configuration:
      Type: Senza::StupsAutoConfiguration # auto-detect network setup

  # will create a launch configuration and auto scaling group with scaling triggers
  - AppServer:
      Type: Senza::TaupageAutoScalingGroup
      InstanceType: {{ instance_type }}
      SecurityGroups:
        - app-{{application_id}}
      ElasticLoadBalancer: AppLoadBalancer
      TaupageConfig:
        runtime: Docker
        source: "{{ docker_image }}:{{=<% %>=}}{{Arguments.ImageVersion}}<%={{ }}=%>"
        ports:
          {{http_port}}: {{http_port}}

  # creates an ELB entry and Route53 domains to this ELB
  - AppLoadBalancer:
      Type: Senza::WeightedDnsElasticLoadBalancer
      HTTPPort: {{http_port}}
      HealthCheckPath: {{http_health_check_path}}
      SecurityGroups:
        - app-{{application_id}}-lb
'''


def prompt(variables: dict, var_name, *args, **kwargs):
    if var_name not in variables:
        variables[var_name] = click.prompt(*args, **kwargs)


def gather_user_variables(variables):
    prompt(variables, 'application_id', 'Application ID', default='hello-world')
    prompt(variables, 'docker_image', 'Docker image', default='stups/hello-world')
    prompt(variables, 'http_port', 'HTTP port', default=8080, type=int)
    prompt(variables, 'http_health_check_path', 'HTTP health check path', default='/')
    prompt(variables, 'instance_type', 'EC2 instance type', default='t2.micro')
    return variables


def generate_definition(variables):
    definition_yaml = pystache.render(TEMPLATE, variables)
    definition = yaml.safe_load(definition_yaml)
    return definition
