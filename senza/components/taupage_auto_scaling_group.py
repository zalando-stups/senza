
import click
import pierone.api
import textwrap
import yaml
import json
import sys
import re

from senza.aws import resolve_referenced_resource
from senza.components.auto_scaling_group import component_auto_scaling_group
from senza.docker import docker_image_exists
from senza.utils import ensure_keys


_AWS_FN_RE = re.compile(r"('[{]{2} (.*?) [}]{2}')", re.DOTALL)


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

    userdata = generate_user_data(taupage_config, args.region)

    config_name = configuration["Name"] + "Config"
    ensure_keys(definition, "Resources", config_name, "Properties", "UserData")
    definition["Resources"][config_name]["Properties"]["UserData"]["Fn::Base64"] = userdata

    return definition


def generate_user_data(taupage_config, region):
    """
    Generates the CloudFormation "UserData" field.
    It looks for AWS functions such as Fn:: and Ref and generates the appropriate UserData json field,
    It leaves nodes representing AWS functions or refs unmodified and converts into text everything else.
    Example::
      environment:
        S3_BUCKET: {"Ref": "ExhibitorBucket"}
        S3_PREFIX: exhibitor

    transforms into::
      {"Fn::Join": ["", "environment:\n  S3_BUCKET: ", {"Ref": "ExhibitorBucket"}, "\n  S3_PREFIX: exhibitor"]}

    :param taupage_config:
    :return:
    """

    def is_aws_fn(name):
        try:
            return name == "Ref" or (isinstance(name, str) and name.startswith("Fn::"))
        except:
            return False

    def transform(node):
        """Transform AWS functions and refs into an string representation for later split and substitution"""

        if isinstance(node, dict):
            num_keys = len(node)
            if 'Stack' in node and 'Output' in node:
                return resolve_referenced_resource(node, region)
            if num_keys > 0:
                key = next(iter(node.keys()))
                if num_keys == 1 and is_aws_fn(key):
                    return "".join(["{{ ", json.dumps(node), " }}"])
                else:
                    return {key: transform(value) for key, value in node.items()}
            else:
                return node
        elif isinstance(node, list):
            return [transform(subnode) for subnode in node]
        else:
            return node

    def split(text):
        """Splits yaml text into text and AWS functions/refs"""

        parts = []
        last_pos = 0
        for m in _AWS_FN_RE.finditer(text):
            parts += [text[last_pos:m.start(1)], json.loads(m.group(2))]
            last_pos = m.end(1)
        parts += [text[last_pos:]]
        return parts

    yaml_text = yaml.dump(transform(taupage_config), width=sys.maxsize, default_flow_style=False)

    parts = split("#taupage-ami-config\n" + yaml_text)

    if len(parts) == 1:
        return parts[0]
    else:
        return {"Fn::Join": ["", parts]}
