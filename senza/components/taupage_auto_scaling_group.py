
import click
import pierone.api
import textwrap
import yaml

from senza.components.auto_scaling_group import component_auto_scaling_group
from senza.docker import docker_image_exists
from senza.utils import ensure_keys


def check_docker_image_exists(docker_image: pierone.api.DockerImage):
    if 'pierone' in docker_image.registry:
        try:
            exists = pierone.api.image_exists('pierone', docker_image)
        except pierone.api.Unauthorized:
            msg = textwrap.dedent('''
            Unauthorized: Cannot check whether Docker image "{}" exists in Pier One Docker registry.
            Please generate a "pierone" OAuth access token using "pierone login".
            Alternatively you can skip this check using the "--force" option.
            '''.format(docker_image)).strip()
            raise click.UsageError(msg)

    else:
        exists = docker_image_exists(str(docker_image))
    if not exists:
        raise click.UsageError('Docker image "{}" does not exist'.format(docker_image))


def component_taupage_auto_scaling_group(definition, configuration, args, info, force, account_info):
    # inherit from the normal auto scaling group but discourage user info and replace with a Taupage config
    if 'Image' not in configuration:
        configuration['Image'] = 'LatestTaupageImage'
    definition = component_auto_scaling_group(definition, configuration, args, info, force, account_info)

    taupage_config = configuration['TaupageConfig']

    if 'notify_cfn' not in taupage_config:
        taupage_config['notify_cfn'] = {'stack': '{}-{}'.format(info["StackName"], info["StackVersion"]),
                                        'resource': configuration['Name']}

    if 'application_id' not in taupage_config:
        taupage_config['application_id'] = info['StackName']

    if 'application_version' not in taupage_config:
        taupage_config['application_version'] = info['StackVersion']

    runtime = taupage_config.get('runtime')
    if runtime != 'Docker':
        raise click.UsageError('Taupage only supports the "Docker" runtime currently')

    source = taupage_config.get('source')
    if not source:
        raise click.UsageError('The "source" property of TaupageConfig must be specified')

    docker_image = pierone.api.DockerImage.parse(source)

    if not force and docker_image.registry:
        check_docker_image_exists(docker_image)

    userdata = "#taupage-ami-config\n" + yaml.dump(taupage_config, default_flow_style=False)

    config_name = configuration["Name"] + "Config"
    ensure_keys(definition, "Resources", config_name, "Properties", "UserData")
    definition["Resources"][config_name]["Properties"]["UserData"]["Fn::Base64"] = userdata

    return definition
