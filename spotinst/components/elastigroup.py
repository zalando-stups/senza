from senza.aws import resolve_security_groups
from senza.utils import ensure_keys

SPOTINST_LAMBDA_FORMATION_ARN = 'arn:aws:lambda:{}:178579023202:function:spotinst-cloudformation'


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
    extract_load_balancer_name(elastigroup_config)
    extract_image_id(elastigroup_config)
    extract_security_group_ids(elastigroup_config, args)

    # cfn definition
    definition["Resources"][config_name] = {
        "Type": "Custom::elastigroup",
        "Properties": {
            "ServiceToken": create_service_token(args.region),
            "accessToken": _extract_spotinst_access_token(definition),
            "group": elastigroup_config
        }
    }

    return definition


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
        if "Image" in launch_spec_config.keys():
            image_ref = launch_spec_config.pop("Image")
            image_id = {"Fn::FindInMap": ["Images", {"Ref": "AWS::Region"}, image_ref]}
            launch_spec_config["imageId"] = image_id


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
