import pytest
import requests
import responses
from mock import MagicMock
from senza.definitions import AccountArguments
from spotinst import MissingSpotinstAccount
from spotinst.components.elastigroup import component_elastigroup, ELASTIGROUP_DEFAULT_PRODUCT, \
    ELASTIGROUP_DEFAULT_STRATEGY, ELASTIGROUP_DEFAULT_CAPACITY, resolve_account_id, SPOTINST_API_URL


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


def test_spotinst_account_resolution():
    mock_info = MagicMock()
    mock_info.AccountID = "12345"
    with responses.RequestsMock() as rsps:
        rsps.add(rsps.GET, '{}/setup/account/'.format(SPOTINST_API_URL), status=200,
                 json={"response": {
                     "items": [
                         {"accountId": "act-1234abcd", "name": "aws:" + mock_info.AccountID},
                         {"accountId": "act-xyz", "name": "aws:54321"}
                     ],
                 }})

        account_id = resolve_account_id("fake-token", mock_info)
        assert account_id == "act-1234abcd"


def test_spotinst_account_resolution_failure():
    with pytest.raises(MissingSpotinstAccount):
        mock_info = MagicMock()
        mock_info.AccountID = "12345"
        with responses.RequestsMock() as rsps:
            rsps.add(rsps.GET, '{}/setup/account/'.format(SPOTINST_API_URL), status=200,
                     json={"response": {
                         "items": [
                             {"accountId": "act-foo", "name": "aws:xyz"},
                             {"accountId": "act-bar", "name": "aws:zbr"}
                         ],
                     }})

            resolve_account_id("fake-token", mock_info)
