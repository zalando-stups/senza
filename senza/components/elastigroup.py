"""
Functions to create Spotinst Elastigroups
"""

import sys

import click
import pierone
import requests

import senza
from senza.aws import resolve_security_groups
from senza.components.auto_scaling_group import normalize_network_threshold
from senza.components.taupage_auto_scaling_group import check_application_id, check_application_version, \
    check_docker_image_exists, generate_user_data
from senza.utils import ensure_keys, CROSS_STACK_POLICY_NAME
from senza.spotinst import MissingSpotinstAccount
import senza.manaus.iam

ELASTIGROUP_RESOURCE_TYPE = 'Custom::elastigroup'
SPOTINST_LAMBDA_FORMATION_ARN = 'arn:aws:lambda:{}:178579023202:function:spotinst-cloudformation'
SPOTINST_API_URL = 'https://api.spotinst.io'
ELASTIGROUP_DEFAULT_STRATEGY = {
    "risk": 100,
    "availabilityVsCost": "balanced",
    "utilizeReservedInstances": True,
    "fallbackToOd": True,
}
ELASTIGROUP_DEFAULT_PRODUCT = "Linux/UNIX"


def get_instance_profile_from_definition(definition, elastigroup_config):
    launch_spec = elastigroup_config["compute"]["launchSpecification"]

    if "iamRole" not in launch_spec:
        return None

    if "name" in launch_spec["iamRole"]:
        if isinstance(launch_spec["iamRole"]["name"], dict):
            instance_profile_id = launch_spec["iamRole"]["name"]["Ref"]
            instance_profile = definition["Resources"].get(instance_profile_id, None)
            if instance_profile is None:
                raise click.UsageError("Instance Profile referenced is not present in Resources")

            if instance_profile["Type"] != "AWS::IAM::InstanceProfile":
                raise click.UsageError(
                    "Instance Profile references a Resource that is not of type 'AWS::IAM::InstanceProfile'")

            return instance_profile

    return None


def get_instance_profile_role(instance_profile, definition):
    roles = instance_profile["Properties"]["Roles"]
    if isinstance(roles[0], dict):
        role_id = roles[0]["Ref"]
        role = definition["Resources"].get(role_id, None)
        if role is None:
            raise click.UsageError("Instance Profile references a Role that is not present in Resources")

        if role["Type"] != "AWS::IAM::Role":
            raise click.UsageError("Instance Profile Role references a Resource that is not of type 'AWS::IAM::Role'")

        return role

    return None


def create_cross_stack_policy_document():
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "cloudformation:SignalResource",
                    "cloudformation:DescribeStackResource"
                ],
                "Resource": "*"
            }
        ]
    }


def find_or_create_cross_stack_policy():
    return senza.manaus.iam.find_or_create_policy(policy_name=CROSS_STACK_POLICY_NAME,
                                                  policy_document=create_cross_stack_policy_document(),
                                                  description="Required permissions for EC2 instances created by "
                                                              "Spotinst to signal CloudFormation")


def patch_cross_stack_policy(definition, elastigroup_config):
    """
    This function will make sure that the role used in the Instance Profile includes the Cross Stack API
    requests policy, needed for Elastigroups to run as expected.
    """
    instance_profile = get_instance_profile_from_definition(definition, elastigroup_config)
    if instance_profile is None:
        return

    instance_profile_role = get_instance_profile_role(instance_profile, definition)
    if instance_profile_role is None:
        return

    cross_stack_policy = find_or_create_cross_stack_policy()

    role_properties = instance_profile_role["Properties"]
    managed_policies_set = set(role_properties.get("ManagedPolicyArns", []))
    managed_policies_set.add(cross_stack_policy["Arn"])
    role_properties["ManagedPolicyArns"] = list(managed_policies_set)


def component_elastigroup(definition, configuration, args, info, force, account_info):
    """
    This component creates a Spotinst Elastigroup CloudFormation custom resource template.
    - For a high level overview see; https://spotinst.com/workload-management/elastigroup/
    - For the API reference see; http://api.spotinst.com/elastigroup/amazon-web-services/create/
    - For the CloudFormation integration see; http://blog.spotinst.com/2016/04/05/elastigroup-cloudformation/
    """
    definition = ensure_keys(ensure_keys(definition, "Resources"), "Mappings", "Senza", "Info")
    if "SpotinstAccessToken" not in definition["Mappings"]["Senza"]["Info"]:
        raise click.UsageError("You have to specify your SpotinstAccessToken attribute inside the SenzaInfo "
                               "to be able to use Elastigroups")
    configuration = ensure_keys(configuration, "Elastigroup")

    # launch configuration
    elastigroup_config = configuration["Elastigroup"]
    ensure_keys(elastigroup_config, "scheduling")
    ensure_keys(elastigroup_config, "thirdPartiesIntegration")

    fill_standard_tags(definition, elastigroup_config)
    ensure_default_strategy(elastigroup_config)
    ensure_default_product(elastigroup_config)
    ensure_instance_monitoring(elastigroup_config)

    extract_subnets(configuration, elastigroup_config, account_info)
    extract_user_data(configuration, elastigroup_config, info, force, account_info)
    extract_load_balancer_name(configuration, elastigroup_config)
    extract_public_ips(configuration, elastigroup_config)
    extract_image_id(elastigroup_config)
    extract_security_group_ids(configuration, elastigroup_config, args)
    extract_instance_types(configuration, elastigroup_config)
    extract_autoscaling_capacity(configuration, elastigroup_config)
    extract_auto_scaling_rules(configuration, elastigroup_config)
    extract_block_mappings(configuration, elastigroup_config)
    extract_instance_profile(args, definition, configuration, elastigroup_config)
    patch_cross_stack_policy(definition, elastigroup_config)
    # cfn definition
    access_token = _extract_spotinst_access_token(definition)
    config_name = configuration["Name"]
    definition["Resources"][config_name] = {
        "Type": ELASTIGROUP_RESOURCE_TYPE,
        "Properties": {
            "ServiceToken": create_service_token(args.region),
            "accessToken": access_token,
            "accountId": extract_spotinst_account_id(access_token, definition, account_info),
            "group": elastigroup_config
        }
    }

    if "SpotPrice" in configuration:
        print("warning: SpotPrice is ignored when using Senza::Elastigroup", file=sys.stderr)
    return definition


def extract_block_mappings(configuration, elastigroup_config):
    """
    This function converts a Senza BlockDeviceMappings section into the matching section of the Elastigroup
    If there's a launchSpecification.blockDeviceMappings section already it's left untouched
    """
    if "BlockDeviceMappings" not in configuration:
        return
    elastigroup_config = ensure_keys(elastigroup_config, "compute", "launchSpecification")
    launch_spec = elastigroup_config["compute"]["launchSpecification"]
    if "blockDeviceMappings" in launch_spec:
        return
    block_device_mappings = configuration.pop("BlockDeviceMappings")
    elastigroup_mappings = []
    for mapping in block_device_mappings:
        elastigroup_mappings.append({
            "deviceName": mapping["DeviceName"],
            "ebs": {
                "deleteOnTermination": True,
                "volumeType": "gp2",
                "volumeSize": mapping["Ebs"]["VolumeSize"]
            }
        })
    if elastigroup_mappings:
        launch_spec["blockDeviceMappings"] = elastigroup_mappings


def extract_auto_scaling_rules(configuration, elastigroup_config):
    """
    This function will convert Senza's auto scaling settings and create the matching scaling rules
    for the Elastigroup
    If there's already a scaling configuration it will be left untouched
    """
    if "scaling" in elastigroup_config:
        return
    auto_scaling = configuration.get("AutoScaling", None)
    scaling = {}
    if auto_scaling:
        adjustment = auto_scaling.get("ScalingAdjustment", 1)
        cooldown = auto_scaling.get("Cooldown", 60)

        # Scale up
        scale_up_adjustment = int(auto_scaling.get("ScaleUpAdjustment", adjustment))
        scale_up_cooldown = auto_scaling.get("ScaleUpCooldown", cooldown)
        if "ScaleUpThreshold" in auto_scaling:
            scaling["up"] = [create_scale_rule(auto_scaling, "gte", auto_scaling["ScaleUpThreshold"],
                                               scale_up_adjustment, scale_up_cooldown)]

        # Scale down
        scale_down_adjustment = int(auto_scaling.get("ScaleDownAdjustment", adjustment))
        scale_down_cooldown = auto_scaling.get("ScaleDownCooldown", cooldown)
        if "ScaleDownThreshold" in auto_scaling:
            scaling["down"] = [create_scale_rule(auto_scaling, "lt", auto_scaling["ScaleDownThreshold"],
                                                 scale_down_adjustment, scale_down_cooldown)]

    elastigroup_config["scaling"] = scaling


def normalize_threshold(metric_type, threshold):
    """
    This function returns a tuple with the actual threshold and the respective unit
    The returned unit is "percent" except when the metric_type is one of the Network metrics, in which case
    the parsed and normalized unit is returned.
    """
    if metric_type.startswith("Network"):
        normalized_threshold = normalize_network_threshold(threshold)
        return normalized_threshold[0], normalized_threshold[1]
    return threshold, "percent"


def create_scale_rule(auto_scaling, operator, threshold, adjustment, cooldown):
    """
    This function creates an Elastigroup scaling rule from Senza definitions
    :return: an object valid for Spotinst's scaling rules
    """
    metric_type = auto_scaling.get("MetricType", "CPU")
    valid_metrics = {"CPU": "CPUUtilization", "NetworkIn": "NetworkIn", "NetworkOut": "NetworkOut"}
    ops = {"gt": ">", "gte": ">=", "lt": "<", "lte": "<="}
    if metric_type.lower() not in map(lambda t: t.lower(), valid_metrics.keys()):
        raise click.UsageError('Auto scaling MetricType "{}" not supported.'.format(metric_type))
    threshold, unit = normalize_threshold(metric_type, threshold)
    period = int(auto_scaling.get("Period", 300))
    evaluation_periods = int(auto_scaling.get("EvaluationPeriods", 2))
    statistic = auto_scaling.get("Statistic", "average")
    statistic = statistic[0].lower() + statistic[1:]  # fix case for spotinst API :(

    return {
        "policyName": "Scale if {} {} {} {} for {} minutes ({})".format(
            metric_type,
            ops.get(operator, "kind of"),
            threshold,
            unit,
            (period / 60) * evaluation_periods,
            statistic
        ),
        "metricName": valid_metrics[metric_type],
        "statistic": statistic,
        "unit": unit,
        "threshold": threshold,
        "namespace": "AWS/EC2",
        "dimensions": [{"name": "InstanceId"}],
        "period": period,
        "evaluationPeriods": evaluation_periods,
        "cooldown": cooldown,
        "action": {
            "type": "adjustment",
            "adjustment": adjustment
        },
        "operator": operator
    }


def ensure_instance_monitoring(elastigroup_config):
    """
    This functions will set the monitoring property to True if not set already in the compute.launchSpecification
    section. This enables EC2 enhanced monitoring, which is also the general STUPS behavior
    """
    elastigroup_config = ensure_keys(elastigroup_config, "compute", "launchSpecification")
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


def extract_autoscaling_capacity(configuration, elastigroup_config):
    """
    This function will set the Spotinst capacity from the Senza AutoScaling settings.
    It will add a default capacity of 1 if none is present.
    The target capacity will be adjusted to be within the minimum and maximum boundaries
    If there's already a capacity section it will be left untouched
    """
    if "capacity" in elastigroup_config:
        return
    auto_scaling = configuration.get("AutoScaling", None)
    target = 1
    minimum = 1
    maximum = 1
    if auto_scaling:
        minimum = int(auto_scaling.get("Minimum", minimum))
        maximum = int(auto_scaling.get("Maximum", maximum))
        target = min(max(minimum, int(auto_scaling.get("DesiredCapacity", 1))), maximum)

    elastigroup_config["capacity"] = {"target": target, "minimum": minimum, "maximum": maximum}


def ensure_default_product(elastigroup_config):
    """
    This function ensures that the compute.product attribute for the Elastigroup is defined with a default value.
    See ELASTIGROUP_DEFAULT_PRODUCT
    """
    elastigroup_config = ensure_keys(elastigroup_config, "compute")
    if "product" in elastigroup_config["compute"]:
        return
    elastigroup_config["compute"]["product"] = ELASTIGROUP_DEFAULT_PRODUCT


def fill_standard_tags(definition, elastigroup_config):
    """
    This function adds the default STUPS EC2 Tags when none are defined in the Elastigroup. It also sets the
    Elastigroup name attribute to the same value as the EC2 Name tag if found empty.
    The default STUPS EC2 Tags are Name, StackName and StackVersion
    """
    # Tag keys are case-sensitive: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/Using_Tags.html
    standard_tags = {"Name", "StackName", "StackVersion"}
    elastigroup_config = ensure_keys(elastigroup_config, "compute", "launchSpecification")
    name = definition["Mappings"]["Senza"]["Info"]["StackName"]
    version = definition["Mappings"]["Senza"]["Info"]["StackVersion"]
    full_name = "{}-{}".format(name, version)

    tags = []
    if "tags" in elastigroup_config["compute"]["launchSpecification"]:
        tags = elastigroup_config["compute"]["launchSpecification"]["tags"]

    # Remove any standard tags specified in ElastiGroup configuration
    tags = list(filter(lambda tag: tag["tagKey"] not in standard_tags, tags))

    # Add standard tags from Senza definition
    tags.extend([
        {"tagKey": "Name", "tagValue": full_name},
        {"tagKey": "StackName", "tagValue": name},
        {"tagKey": "StackVersion", "tagValue": version}
    ])

    elastigroup_config["compute"]["launchSpecification"]["tags"] = tags

    if elastigroup_config.get("name", "") == "":
        elastigroup_config["name"] = full_name


def extract_subnets(configuration, elastigroup_config, account_info):
    """
    This fills in the subnetIds and region attributes of the Spotinst elastigroup, in case they're not defined already
    The subnetIds are discovered by Senza::StupsAutoConfiguration and the region is provided by the AccountInfo object
    """
    elastigroup_config = ensure_keys(elastigroup_config, "compute")
    subnet_ids = elastigroup_config["compute"].get("subnetIds", [])
    target_region = elastigroup_config.get("region", account_info.Region)
    if not subnet_ids:
        subnet_set = "LoadBalancerSubnets" if configuration.get("AssociatePublicIpAddress", False) else "ServerSubnets"
        elastigroup_config["compute"]["subnetIds"] = {"Fn::FindInMap": [subnet_set, {"Ref": "AWS::Region"}, "Subnets"]}
    elastigroup_config["region"] = target_region


def extract_user_data(configuration, elastigroup_config, info: dict, force, account_info):
    """
    This function converts a classic TaupageConfig into a base64 encoded value for the
    compute.launchSpecification.userData
    See https://api.spotinst.com/elastigroup/amazon-web-services/create/#compute.launchSpecification.userData
    Any existing TaupageConfig will _always_ overwrite the userData for the Elastigroup
    """
    elastigroup_config = ensure_keys(elastigroup_config, "compute", "launchSpecification")
    taupage_config = configuration.get("TaupageConfig", None)
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

        elastigroup_config["compute"]["launchSpecification"]["userData"] = \
            {"Fn::Base64": generate_user_data(taupage_config, account_info.Region)}


def extract_load_balancer_name(configuration, elastigroup_config: dict):
    """
    This function identifies whether a senza ELB is configured,
    if so it transforms it into a Spotinst Elastigroup balancer API configuration
    If there's already a Spotinst launchSpecification present it is left untouched
    It also handles the health check definitions (type and grace period) giving precedence to any existing Elastigroup
    defintions.
    """

    elastigroup_config = ensure_keys(elastigroup_config, "compute", "launchSpecification")
    launch_spec_config = elastigroup_config["compute"]["launchSpecification"]
    health_check_type = "EC2"

    if "loadBalancersConfig" not in launch_spec_config.keys():
        load_balancers = []

        if "ElasticLoadBalancer" in configuration:
            load_balancer_refs = configuration.pop("ElasticLoadBalancer")
            health_check_type = "ELB"
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
        if "ElasticLoadBalancerV2" in configuration:
            health_check_type = "TARGET_GROUP"
            load_balancer_refs = configuration.pop("ElasticLoadBalancerV2")
            custom_target_groups = configuration.pop("TargetGroupARNs", None)
            if custom_target_groups:
                for custom_target_group in custom_target_groups:
                    load_balancers.append({
                        "arn": custom_target_group,
                        "type": "TARGET_GROUP"
                    })
            else:
                if isinstance(load_balancer_refs, str):
                    load_balancers.append({
                        "arn": {"Ref": load_balancer_refs + 'TargetGroup'},
                        "type": "TARGET_GROUP"
                    })
                elif isinstance(load_balancer_refs, list):
                    for load_balancer_ref in load_balancer_refs:
                        load_balancers.append({
                            "arn": {"Ref": load_balancer_ref + "TargetGroup"},
                            "type": "TARGET_GROUP"
                        })

        if len(load_balancers) > 0:
            launch_spec_config["loadBalancersConfig"] = {"loadBalancers": load_balancers}

    health_check_type = launch_spec_config.get("healthCheckType",
                                               configuration.get("HealthCheckType", health_check_type))
    grace_period = launch_spec_config.get("healthCheckGracePeriod",
                                          configuration.get('HealthCheckGracePeriod', 300))
    launch_spec_config["healthCheckType"] = health_check_type
    launch_spec_config["healthCheckGracePeriod"] = grace_period


def extract_public_ips(configuration, elastigroup_config):
    """
    This function will setup the Spotinst Elastigroup to use Public IPs if the
    Senza AssociatePublicIpAddress is set to True.
    If there's already a compute.launchSpecification.networkInterfaces config it is left untouched
    """
    elastigroup_config = ensure_keys(elastigroup_config, "compute", "launchSpecification")
    if configuration.pop("AssociatePublicIpAddress", False):
        launch_spec_config = elastigroup_config["compute"]["launchSpecification"]
        if "networkInterfaces" not in launch_spec_config.keys():
            launch_spec_config["networkInterfaces"] = [
                {
                    "deleteOnTermination": True,
                    "deviceIndex": 0,
                    "associatePublicIpAddress": True
                }
            ]


def extract_image_id(elastigroup_config: dict):
    """
    This function identifies whether a senza formatted AMI mapping is configured,
    if so it transforms it into a Spotinst Elastigroup AMI API configuration
    """
    elastigroup_config = ensure_keys(elastigroup_config, "compute", "launchSpecification")
    launch_spec_config = elastigroup_config["compute"]["launchSpecification"]

    if "imageId" not in launch_spec_config.keys():
        launch_spec_config["imageId"] = {"Fn::FindInMap": ["Images", {"Ref": "AWS::Region"}, "LatestTaupageImage"]}


def extract_security_group_ids(configuration, elastigroup_config: dict, args):
    """
    This function identifies whether a senza formatted EC2-sg (by name) is configured,
    if so it transforms it into a Spotinst Elastigroup EC2-sq (by id) API configuration
    If there's already a compute.launchSpecification.securityGroupIds config it's left unchanged
    """
    elastigroup_config = ensure_keys(elastigroup_config, "compute", "launchSpecification")
    launch_spec_config = elastigroup_config["compute"]["launchSpecification"]

    security_group_ids = []
    if "securityGroupIds" not in launch_spec_config.keys():
        if "SecurityGroups" in configuration.keys():
            security_groups_ref = configuration.pop("SecurityGroups")

            if isinstance(security_groups_ref, str):
                security_group_ids = resolve_security_groups([security_groups_ref], args.region)

            elif isinstance(security_groups_ref, list):
                security_group_ids = resolve_security_groups(security_groups_ref, args.region)

            if len(security_group_ids) > 0:
                launch_spec_config["securityGroupIds"] = security_group_ids


def extract_instance_types(configuration, elastigroup_config):
    """
    This function will set up the Elastigroup instance type, both for on-demand and spot. If there
    are no SpotAlternatives the Elastigroup will have the same ondemand type as spot alternative
    If there's already a compute.instanceTypes config it will be left untouched
    """
    elastigroup_config = ensure_keys(elastigroup_config, "compute")
    compute_config = elastigroup_config["compute"]

    if "InstanceType" not in configuration:
        raise click.UsageError("You need to specify the InstanceType attribute to be able to use Elastigroups")
    instance_type = configuration.pop("InstanceType")
    spot_alternatives = configuration.pop("SpotAlternatives", None)
    if "instanceTypes" not in compute_config:
        instance_types = {}
        instance_types.update({"ondemand": instance_type})
        if spot_alternatives:
            instance_types.update({"spot": spot_alternatives})
        else:
            instance_types.update({"spot": [instance_type]})
        compute_config["instanceTypes"] = instance_types


def extract_instance_profile(args, definition, configuration, elastigroup_config):
    """
    Resolves the Senza IAM role or instance profile into the appropriate Spotinst launchSpecification.iamRole
    settings.
    If only IAM roles are specified, a new instance profile is created and the Elastigroup definition will have a
    reference to the newly created instance profile.
    If the launchSpecification already has the iamRole defined it is left untouched
    When the Senza manifest includes both the IAMRoles and the IamInstanceProfile attributes the IAMRoles takes
    precedence.
    The IamInstanceProfile can specify either the ARN or just the instance profile name. This function will accept both
    """
    elastigroup_config = ensure_keys(elastigroup_config, "compute", "launchSpecification")
    launch_spec = elastigroup_config["compute"]["launchSpecification"]
    if "iamRole" in launch_spec:
        return
    if "IamRoles" in configuration:
        logical_id = senza.components.auto_scaling_group.handle_iam_roles(definition, configuration, args)
        launch_spec["iamRole"] = {"name": {"Ref": logical_id}}
    elif "IamInstanceProfile" in configuration:
        logical_id = configuration["IamInstanceProfile"]
        attribute = "arn" if logical_id.startswith("arn:aws:iam::") else "name"
        launch_spec["iamRole"] = {attribute: logical_id}


def create_service_token(region: str):
    """
    dynamically creates the AWS Lambda service token based on the region
    """
    return SPOTINST_LAMBDA_FORMATION_ARN.format(region)  # cannot use cfn intrinsic function


def _extract_spotinst_access_token(definition: dict):
    """
    extract the provided access token
    """
    return definition["Mappings"]["Senza"]["Info"].pop("SpotinstAccessToken")


def extract_spotinst_account_id(access_token: str, definition: dict, account_info):
    """
    if present, return the template defined Spotinst target account id or use the Spotinst API to
    list the accounts and return the first account found
    """
    template_account_id = definition["Mappings"]["Senza"]["Info"].get("SpotinstAccountId")
    if not template_account_id:
        template_account_id = resolve_account_id(access_token, account_info.AccountID)
    return template_account_id


def resolve_account_id(access_token, account_id):
    """
    This function will call the remote Spotinst API using the provided Token and query the
    cloud account which matches the provided AWS Account ID. In case there are multiple matches,
    the first one is returned
    :param access_token: The Spotinst access token that can be created using the console
    :param account_id: The target AWS account ID
    :return: The Spotinst accountId that matched the target AWS account ID
    """
    headers = {
        "Authorization": "Bearer {}".format(access_token),
        "Content-Type": "application/json"
    }
    response = requests.get('{}/setup/account?awsAccountId={}'.format(SPOTINST_API_URL, account_id),
                            headers=headers, timeout=5)
    response.raise_for_status()
    data = response.json()
    accounts = data.get("response", {}).get("items", [])
    if not accounts:
        raise MissingSpotinstAccount(account_id)
    cloud_account = next(iter(accounts))
    return cloud_account["accountId"]
