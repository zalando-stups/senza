from mock import MagicMock

from senza.definitions import AccountArguments
from spotinst.components.elastigroup import component_elastigroup, ELASTIGROUP_DEFAULT_PRODUCT, \
    ELASTIGROUP_DEFAULT_STRATEGY, ELASTIGROUP_DEFAULT_CAPACITY


def test_component_elastigroup_defaults(monkeypatch):
    configuration = {
        "Name": "eg1",
        "Elastigroup": {
            "compute": {
                "instanceTypes": {
                    "ondemand": "big",
                    "spot": ["smaller", "small"]
                },
                "launchSpecification": {
                    "SecurityGroups": "sg1",
                    "ElasticLoadBalancer": "lb1"
                }
            }
        }
    }
    args = MagicMock()
    args.region = "reg1"
    info = {'StackName': 'foobar', 'StackVersion': '0.1', 'SpotinstAccessToken': 'token1'}
    subnets = ["sn1", "sn2", "sn3"]
    server_subnets = {"reg1": {"Subnets": subnets}}
    senza = {"Info": info}
    mappings = {"Senza": senza, "ServerSubnets": server_subnets}
    definition = {"Resources": {}, "Mappings": mappings}
    mock_sg = MagicMock()
    mock_sg.return_value = "sg1"
    monkeypatch.setattr('senza.aws.resolve_security_group', mock_sg)

    resolve_account_id = MagicMock()
    resolve_account_id.return_value = 'act-12345abcdef'
    monkeypatch.setattr('spotinst.components.elastigroup.resolve_account_id', resolve_account_id)

    result = component_elastigroup(definition, configuration, args, info, False, AccountArguments('reg1'))

    properties = result["Resources"]["eg1Config"]["Properties"]
    assert properties["accountId"] == 'act-12345abcdef'
    assert properties["group"]["capacity"] == ELASTIGROUP_DEFAULT_CAPACITY
    launch_specification = properties["group"]["compute"]["launchSpecification"]
    assert launch_specification["monitoring"]
    assert launch_specification["securityGroupIds"] == ["sg1"]
    tags = launch_specification["tags"]
    assert {'tagKey': 'Name', 'tagValue': 'foobar-0.1'} in tags
    assert {'tagKey': 'StackName', 'tagValue': 'foobar'} in tags
    assert {'tagKey': 'StackVersion', 'tagValue': '0.1'} in tags
    assert properties["group"]["compute"]["product"] == ELASTIGROUP_DEFAULT_PRODUCT
    assert properties["group"]["compute"]["subnetIds"] == subnets
    assert properties["group"]["region"] == "reg1"
    assert properties["group"]["strategy"] == ELASTIGROUP_DEFAULT_STRATEGY

    assert "scaling" in properties["group"]
    assert "scheduling" in properties["group"]
    assert "thirdPartiesIntegration" in properties["group"]


