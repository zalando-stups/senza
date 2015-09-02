import click
from unittest.mock import MagicMock
from senza.components import get_component
from senza.components.iam_role import component_iam_role, get_merged_policies
from senza.components.elastic_load_balancer import component_elastic_load_balancer
from senza.components.stups_auto_configuration import component_stups_auto_configuration
from senza.components.redis_node import component_redis_node
from senza.components.redis_cluster import component_redis_cluster

def test_invalid_component():
    assert get_component('Foobar') is None


def test_component_iam_role(monkeypatch):
    configuration = {
        'Name': 'MyRole',
        'MergePoliciesFromIamRoles': ['OtherRole']
    }
    definition = {}
    args = MagicMock()
    args.region = "foo"
    monkeypatch.setattr('senza.components.iam_role.get_merged_policies', MagicMock(return_value=[{'a': 'b'}]))
    result = component_iam_role(definition, configuration, args, MagicMock(), False)

    assert [{'a': 'b'}] == result['Resources']['MyRole']['Properties']['Policies']


def test_get_merged_policies(monkeypatch):
    iam = MagicMock()
    iam.list_role_policies.return_value = {'list_role_policies_response': {'list_role_policies_result': {'policy_names': ['pol1']}}}
    iam.get_role_policy.return_value = {'get_role_policy_response': {'get_role_policy_result': {'policy_document': '{"foo":"bar"}'}}}
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: iam)
    assert [{'PolicyDocument': {'foo': 'bar'}, 'PolicyName': 'pol1'}] == get_merged_policies(['RoleA'], 'myregion')


def test_component_load_balancer_healthcheck(monkeypatch):
    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        "HealthCheckPath": "/healthcheck"
    }
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = "foo"
    monkeypatch.setattr('senza.components.elastic_load_balancer.find_ssl_certificate_arn', mock_string_result)
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    result = component_elastic_load_balancer(definition, configuration, args, info, False)
    # Defaults to HTTP
    assert "HTTP:9999/healthcheck" == result["Resources"]["test_lb"]["Properties"]["HealthCheck"]["Target"]

    # Support own health check port
    configuration["HealthCheckPort"] = "1234"
    result = component_elastic_load_balancer(definition, configuration, args, info, False)
    assert "HTTP:1234/healthcheck" == result["Resources"]["test_lb"]["Properties"]["HealthCheck"]["Target"]
    del(configuration["HealthCheckPort"])

    # Supports other AWS protocols
    configuration["HealthCheckProtocol"] = "TCP"
    result = component_elastic_load_balancer(definition, configuration, args, info, False)
    assert "TCP:9999/healthcheck" == result["Resources"]["test_lb"]["Properties"]["HealthCheck"]["Target"]

    # Will fail on incorrect protocol
    configuration["HealthCheckProtocol"] = "MYFANCYPROTOCOL"
    try:
        component_elastic_load_balancer(definition, configuration, args, info, False)
    except click.UsageError:
        pass
    except:
        assert False, "check for supported protocols returns unknown Exception"
    else:
        assert False, "check for supported protocols failed"



def test_component_load_balancer_idletimeout(monkeypatch):
    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        "ConnectionSettings": {"IdleTimeout": 300}
    }
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = "foo"
    monkeypatch.setattr('senza.components.elastic_load_balancer.find_ssl_certificate_arn', mock_string_result)
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    # issue 105: support additional ELB properties
    result = component_elastic_load_balancer(definition, configuration, args, info, False)
    assert 300 == result["Resources"]["test_lb"]["Properties"]["ConnectionSettings"]["IdleTimeout"]


def test_component_load_balancer_namelength(monkeypatch):
    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        "HealthCheckPath": "/healthcheck"
    }
    info = {'StackName': 'foobar'*5, 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = "foo"
    monkeypatch.setattr('senza.components.elastic_load_balancer.find_ssl_certificate_arn', mock_string_result)
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    result = component_elastic_load_balancer(definition, configuration, args, info, False)
    lb_name = result['Resources']['test_lb']['Properties']['LoadBalancerName']
    assert lb_name == 'foobarfoobarfoobarfoobarfoob-0.1'
    assert len(lb_name) == 32


def test_component_stups_auto_configuration(monkeypatch):
    args = MagicMock()
    args.region = 'myregion'

    configuration = {
        'Name': 'Config',
        'AvailabilityZones': ['az-1']
    }

    sn1 = MagicMock()
    sn1.id = 'sn-1'
    sn1.tags.get.return_value = 'dmz-1'
    sn1.availability_zone = 'az-1'
    sn2 = MagicMock()
    sn2.id = 'sn-2'
    sn2.tags.get.return_value = 'dmz-2'
    sn2.availability_zone = 'az-2'
    sn3 = MagicMock()
    sn3.id = 'sn-3'
    sn3.tags.get.return_value = 'internal-3'
    sn3.availability_zone = 'az-1'
    vpc = MagicMock()
    vpc.get_all_subnets.return_value = [sn1, sn2, sn3]
    image = MagicMock()
    ec2 = MagicMock()
    ec2.get_all_images.return_value = [image]
    monkeypatch.setattr('boto.vpc.connect_to_region', lambda x: vpc)
    monkeypatch.setattr('boto.ec2.connect_to_region', lambda x: ec2)

    result = component_stups_auto_configuration({}, configuration, args, MagicMock(), False)

    assert {'myregion': {'Subnets': ['sn-1']}} == result['Mappings']['LoadBalancerSubnets']
    assert {'myregion': {'Subnets': ['sn-3']}} == result['Mappings']['ServerSubnets']

def test_component_redis_node(monkeypatch):
    mock_string = "foo"

    configuration = {
        "Name": mock_string,
        "SecurityGroups": "",
    }
    info = {'StackName': 'foobar'*5, 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = mock_string
    monkeypatch.setattr('senza.components.redis_node.resolve_security_groups', mock_string_result)

    result = component_redis_node(definition, configuration, args, info, False)

    assert 'RedisCacheCluster' in result['Resources']
    assert mock_string == result['Resources']['RedisCacheCluster']['Properties']['VpcSecurityGroupIds']
    assert mock_string == result['Resources']['RedisCacheCluster']['Properties']['ClusterName']
    assert 1 == result['Resources']['RedisCacheCluster']['Properties']['NumCacheNodes']
    assert 'Engine' in result['Resources']['RedisCacheCluster']['Properties']
    assert 'EngineVersion' in result['Resources']['RedisCacheCluster']['Properties']
    assert 'CacheNodeType' in result['Resources']['RedisCacheCluster']['Properties']
    assert 'CacheSubnetGroupName' in result['Resources']['RedisCacheCluster']['Properties']
    assert 'CacheParameterGroupName' in result['Resources']['RedisCacheCluster']['Properties']

    assert 'RedisSubnetGroup' in result['Resources']
    assert 'SubnetIds' in result['Resources']['RedisSubnetGroup']['Properties']

def test_component_redis_cluster(monkeypatch):
    mock_string = "foo"

    configuration = {
        "Name": mock_string,
        "SecurityGroups": "",
    }
    info = {'StackName': 'foobar'*5, 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = mock_string
    monkeypatch.setattr('senza.components.redis_cluster.resolve_security_groups', mock_string_result)

    result = component_redis_cluster(definition, configuration, args, info, False)

    assert 'RedisReplicationGroup' in result['Resources']
    assert mock_string == result['Resources']['RedisReplicationGroup']['Properties']['SecurityGroupIds']
    assert 2 == result['Resources']['RedisReplicationGroup']['Properties']['NumCacheClusters']
    assert True == result['Resources']['RedisReplicationGroup']['Properties']['AutomaticFailoverEnabled']
    assert 'Engine' in result['Resources']['RedisReplicationGroup']['Properties']
    assert 'EngineVersion' in result['Resources']['RedisReplicationGroup']['Properties']
    assert 'CacheNodeType' in result['Resources']['RedisReplicationGroup']['Properties']
    assert 'CacheSubnetGroupName' in result['Resources']['RedisReplicationGroup']['Properties']
    assert 'CacheParameterGroupName' in result['Resources']['RedisReplicationGroup']['Properties']

    assert 'RedisSubnetGroup' in result['Resources']
    assert 'SubnetIds' in result['Resources']['RedisSubnetGroup']['Properties']
