import click
import pystache
import yaml

TEMPLATE = '''
# basic information for generating and executing this definition
SenzaInfo:
  StackName: {{application_id}}
  Parameters:
    - ImageVersion:
        Description: "Docker image version of MyApp."

# a list of senza components to apply to the definition
SenzaComponents:

  # this basic configuration is required for the other components
  - Configuration:
      Type: Senza::StupsAutoConfiguration # auto-detect network setup

  # will create a launch configuration and auto scaling group with scaling triggers
  - AppServer:
      Type: Senza::TaupageAutoScalingGroup
      InstanceType: t2.medium
      SecurityGroups:
        - app-{{application_id}}
      ElasticLoadBalancer: AppLoadBalancer
      TaupageConfig:
        runtime: Docker
        source: "{{ docker_image }}:{{Arguments.ImageVersion}}"
        ports:
          {{http_port}}: {{http_port}}
        environment:
          SOME_ENV: foobar

  # creates an ELB entry and Route53 domains to this ELB
  - AppLoadBalancer:
      Type: Senza::WeightedDnsElasticLoadBalancer
      HTTPPort: {{http_port}}
      HealthCheckPath: /
      SecurityGroups:
        - app-{{application_id}}-lb
'''


def gather_user_variables(variables):
    app_id = click.prompt('Application ID')
    docker_image = click.prompt('Docker image')
    http_port = click.prompt('HTTP port', default=8080, type=int)
    variables['application_id'] = app_id
    variables['docker_image'] = docker_image
    variables['http_port'] = http_port
    return variables


def generate_definition(variables):
    definition_yaml = pystache.render(TEMPLATE, variables)
    definition = yaml.safe_load(definition_yaml)
    return definition
