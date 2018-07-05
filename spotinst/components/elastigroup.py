"""
Functions to create Spotinst Elastigroups
"""

import base64
import re
import click
import pierone
import requests

from senza.aws import resolve_security_groups
from senza.components.taupage_auto_scaling_group import check_application_id, check_application_version, \
    check_docker_image_exists, generate_user_data
from senza.utils import ensure_keys
from spotinst import MissingSpotinstAccount

SPOTINST_LAMBDA_FORMATION_ARN = 'arn:aws:lambda:{}:178579023202:function:spotinst-cloudformation'
SPOTINST_API_URL = 'https://api.spotinst.io'
ELASTIGROUP_DEFAULT_STRATEGY = {"risk": 100, "availabilityVsCost": "balanced"}
ELASTIGROUP_DEFAULT_CAPACITY = {"target": 1, "minimum": 1, "maximum": 1}
ELASTIGROUP_DEFAULT_PRODUCT = "Linux/UNIX"


def component_elastigroup(definition, configuration, args, info, force, account_info):
    """
    This component creates a Spotinst Elastigroup CloudFormation custom resource template.
    - For a high level overview see; https://spotinst.com/workload-management/elastigroup/
    - For the API reference see; http://api.spotinst.com/elastigroup/amazon-web-services/create/
    - For the CloudFormation integration see; http://blog.spotinst.com/2016/04/05/elastigroup-cloudformation/
    """
    definition = ensure_keys(definition, "Resources")

    config_name = configuration["Name"] + "Config"

    # launch configuration
    elastigroup_config = configuration["Elastigroup"]
    ensure_keys(elastigroup_config, "scaling")
    ensure_keys(elastigroup_config, "scheduling")
    ensure_keys(elastigroup_config, "thirdPartiesIntegration")

    fill_standard_tags(definition, elastigroup_config)
    ensure_default_strategy(elastigroup_config)
    ensure_default_capacity(elastigroup_config)
    ensure_default_product(elastigroup_config)
    ensure_instance_monitoring(elastigroup_config)

    extract_subnets(definition, elastigroup_config, account_info)
    extract_user_data(configuration, elastigroup_config, info, force, account_info)
    extract_load_balancer_name(elastigroup_config)
    extract_image_id(elastigroup_config)
    extract_security_group_ids(elastigroup_config, args)

    # cfn definition
    access_token = _extract_spotinst_access_token(definition)
    definition["Resources"][config_name] = {
        "Type": "Custom::elastigroup",
        "Properties": {
            "ServiceToken": create_service_token(args.region),
            "accessToken": access_token,
            "accountId": extract_spotinst_account_id(access_token, definition, account_info),
            "group": elastigroup_config
        }
    }

    return definition


def ensure_instance_monitoring(elastigroup_config):
    """
    This functions will set the monitoring property to True if not set already in the compute.launchSpecification
    section. This enables EC2 enhanced monitoring, which is also the general STUPS behavior
    """
    if "monitoring" in elastigroup_config["compute"]["launchSpecification"]:
        return
    elastigroup_config["compute"]["launchSpecification"]["monitoring"] = True


def ensure_default_strategy(elastigroup_config):
    """
    This functions will add a default strategy if none is present. See ELASTIGROUP_DEFAULT_STRATEGY
    """
    if "strategy" in elastigroup_config:
        return
    elastigroup_config["strategy"] = ELASTIGROUP_DEFAULT_STRATEGY


def ensure_default_capacity(elastigroup_config):
    """
    This function will add a default capacity section if none is present. See ELASTIGROUP_DEFAULT_CAPACITY
    """
    if "capacity" in elastigroup_config:
        return
    elastigroup_config["capacity"] = ELASTIGROUP_DEFAULT_CAPACITY


def ensure_default_product(elastigroup_config):
    """
    This function ensures that the compute.product attribute for the Elastigroup is defined with a default value.
    See ELASTIGROUP_DEFAULT_PRODUCT
    """
    if "product" in elastigroup_config["compute"]:
        return
    elastigroup_config["compute"]["product"] = ELASTIGROUP_DEFAULT_PRODUCT


def fill_standard_tags(definition, elastigroup_config):
    """
    This function adds the default STUPS EC2 Tags when none are defined in the Elastigroup. It also sets the
    Elastigroup name attribute to the same value as the EC2 Name tag.
    The default STUPS EC2 Tags are Name, StackName and StackVersion
    """
    if "tags" in elastigroup_config["compute"]["launchSpecification"]:
        return

    name = definition["Mappings"]["Senza"]["Info"]["StackName"]
    version = definition["Mappings"]["Senza"]["Info"]["StackVersion"]
    full_name = "{}-{}".format(name, version)
    elastigroup_config["compute"]["launchSpecification"]["tags"] = [
        {"tagKey": "Name", "tagValue": full_name},
        {"tagKey": "StackName", "tagValue": name},
        {"tagKey": "StackVersion", "tagValue": version}
    ]
    if elastigroup_config.get("name", "") == "":
        elastigroup_config["name"] = full_name


def extract_subnets(definition, elastigroup_config, account_info):
    """
    This fills in the subnetIds and region attributes of the Spotinst elastigroup, in case their not defined already
    The subnetIds are discovered by Senza::StupsAutoConfiguration and the region is provided by the AccountInfo object
    """
    subnet_ids = elastigroup_config["compute"].get("subnetIds", [])
    target_region = elastigroup_config.get("region", account_info.Region)
    if not subnet_ids:
        subnet_ids = [subnetId for subnetId in
                      definition["Mappings"]["ServerSubnets"].get(target_region, {}).get("Subnets", [])]
    elastigroup_config["region"] = target_region
    elastigroup_config["compute"]["subnetIds"] = subnet_ids


def extract_user_data(configuration, elastigroup_config, info: dict, force, account_info):
    """
    This function converts a classic TaupageConfig into a base64 encoded value for the
    compute.launchSpecification.userData
    See https://api.spotinst.com/elastigroup/amazon-web-services/create/#compute.launchSpecification.userData
    """
    taupage_config = configuration.get("TaupageConfig", {})
    if taupage_config:
        if 'notify_cfn' not in taupage_config:
            taupage_config['notify_cfn'] = {'stack': '{}-{}'.format(info["StackName"], info["StackVersion"]),
                                            'resource': configuration['Name']}

        if 'application_id' not in taupage_config:
            taupage_config['application_id'] = info['StackName']

        if 'application_version' not in taupage_config:
            taupage_config['application_version'] = info['StackVersion']

        check_application_id(taupage_config['application_id'])
        check_application_version(taupage_config['application_version'])

        runtime = taupage_config.get('runtime')
        if runtime != 'Docker':
            raise click.UsageError('Taupage only supports the "Docker" runtime currently')

        source = taupage_config.get('source')
        if not source:
            raise click.UsageError('The "source" property of TaupageConfig must be specified')

        docker_image = pierone.api.DockerImage.parse(source)

        if not force and docker_image.registry:
            check_docker_image_exists(docker_image)

        user_data = base64.urlsafe_b64encode(generate_user_data(taupage_config, account_info.Region).encode('utf-8'))
        elastigroup_config["compute"]["launchSpecification"]["userData"] = user_data.decode('utf-8')


def extract_load_balancer_name(elastigroup_config: dict):
    """
    This function identifies whether a senza ELB-Classic is configured,
    if so it transforms it into a Spotinst Elastigroup balancer API configuration

    """
    load_balancers = []

    launch_spec_config = elastigroup_config["compute"]["launchSpecification"]

    if "loadBalancersConfig" not in launch_spec_config.keys():
        if "ElasticLoadBalancer" in launch_spec_config.keys():

            load_balancer_refs = launch_spec_config.pop("ElasticLoadBalancer")
            if isinstance(load_balancer_refs, str):
                load_balancers.append({
                    "name": {"Ref": load_balancer_refs},
                    "type": "CLASSIC"
                })

            elif isinstance(load_balancer_refs, list):
                for load_balancer_ref in load_balancer_refs:
                    load_balancers.append({
                        "name": {"Ref": load_balancer_ref},
                        "type": "CLASSIC"
                    })

        if len(load_balancers) > 0:
            launch_spec_config["loadBalancersConfig"] = {"loadBalancers": load_balancers}


def extract_image_id(elastigroup_config: dict):
    """
    This function identifies whether a senza formatted AMI mapping is configured,
    if so it transforms it into a Spotinst Elastigroup AMI API configuration

    """
    launch_spec_config = elastigroup_config["compute"]["launchSpecification"]

    if "imageId" not in launch_spec_config.keys():
        launch_spec_config["imageId"] = {"Fn::FindInMap": ["Images", {"Ref": "AWS::Region"}, "LatestTaupageImage"]}


def extract_security_group_ids(elastigroup_config: dict, args):
    """
    This function identifies whether a senza formatted EC2-sg (by name) is configured,
    if so it transforms it into a Spotinst Elastigroup EC2-sq (by id) API configuration

    """
    security_group_ids = []

    launch_spec_config = elastigroup_config["compute"]["launchSpecification"]

    if "securityGroupIds" not in launch_spec_config.keys():
        if "SecurityGroups" in launch_spec_config.keys():
            security_groups_ref = launch_spec_config.pop("SecurityGroups")

            if isinstance(security_groups_ref, str):
                security_group_ids = resolve_security_groups([security_groups_ref], args.region)

            elif isinstance(security_groups_ref, list):
                security_group_ids = resolve_security_groups(security_groups_ref, args.region)

            if len(security_group_ids) > 0:
                launch_spec_config["securityGroupIds"] = security_group_ids


def create_service_token(region: str):
    """
    dynamically creates the AWS Lambda service token based on the region
    """
    return SPOTINST_LAMBDA_FORMATION_ARN.format(region)  # cannot use cfn intrinsic function


def _extract_spotinst_access_token(definition: dict):
    """
    extract the provided access token
    """
    return definition["Mappings"]["Senza"]["Info"]["SpotinstAccessToken"]


def extract_spotinst_account_id(access_token: str, definition: dict, account_info):
    """
    if present, return the template defined Spotinst target account id or use the Spotinst API to
    list the accounts and return the first account found
    """
    template_account_id = definition["Mappings"]["Senza"]["Info"].get("SpotinstAccountId", "")
    if not template_account_id:
        template_account_id = resolve_account_id(access_token, account_info)
    return template_account_id


def resolve_account_id(access_token, account_info):
    """
    This function will call the remote Spotinst API using the provided Token and obtain the list of registered
    cloud accounts. The cloud accounts are expected to have their name with the pattern "aws:123" where 123 is
    the official AWS account ID.
    The first match to the provided info.AccountID is used to return the Spotinst accountId
    :param access_token: The Spotinst access token that can be created using the console
    :param account_info: The AccountInfo object containing the target AWS account ID
    :return: The Spotinst accountId that matched the target AWS account ID
    """
    headers = {
        "Authorization": "Bearer {}".format(access_token),
        "Content-Type": "application/json"
    }
    response = requests.get('{}/setup/account/'.format(SPOTINST_API_URL), headers=headers, timeout=5)
    response.raise_for_status()
    data = response.json()
    accounts = data.get("response", {}).get("items", [])
    for account in accounts:
        account_id = re.sub(r"(?i)^aws:", "", account["name"])
        if account_info.AccountID == account_id:
            return account["accountId"]
    raise MissingSpotinstAccount(account_info.AccountID)
