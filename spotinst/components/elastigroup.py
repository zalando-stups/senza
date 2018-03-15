from senza.utils import ensure_keys


def component_elastigroup(definition, configuration, args, info, force, account_info):
    definition = ensure_keys(definition, "Resources")

    config_name = configuration["Name"] + "Config"

    # launch configuration
    elastigroup_config = configuration["Elastigroup"]
    extract_load_balancer_name(elastigroup_config)

    # cfn definition
    definition["Resources"][config_name] = {
        "Type": "Custom::elastigroup",
        "Properties": {
            "ServiceToken": configuration["ServiceToken"],
            "accessToken": configuration["accessToken"],
            "group": elastigroup_config
        }
    }

    return definition


def extract_load_balancer_name(elastigroup_config):
    """
    :type elastigroup_config: dict
    """
    load_balancers = []

    launch_spec_config = elastigroup_config["compute"]["launchSpecification"]
    if "ElasticLoadBalancer" in launch_spec_config:
        if isinstance(launch_spec_config["ElasticLoadBalancer"], str):
            load_balancer_ref = launch_spec_config.pop("ElasticLoadBalancer")
            load_balancers.append({
                "name": {"Ref": load_balancer_ref},
                "type": "CLASSIC"
            })

        elif isinstance(launch_spec_config["ElasticLoadBalancer"], list):
            load_balancer_references = launch_spec_config.pop("ElasticLoadBalancer")
            for load_balancer_ref in load_balancer_references:
                load_balancers.append({
                    "name": {"Ref": load_balancer_ref},
                    "type": "CLASSIC"
                })

    if len(load_balancers) > 0:
        launch_spec_config["loadBalancersConfig"] = {"loadBalancers": load_balancers}
