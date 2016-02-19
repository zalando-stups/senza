import click
import pytest
from unittest.mock import MagicMock
from senza.cli import AccountArguments
from senza.components import get_component
from senza.components.iam_role import component_iam_role, get_merged_policies
from senza.components.elastic_load_balancer import component_elastic_load_balancer
from senza.components.weighted_dns_elastic_load_balancer import component_weighted_dns_elastic_load_balancer
from senza.components.stups_auto_configuration import component_stups_auto_configuration
from senza.components.redis_node import component_redis_node
from senza.components.redis_cluster import component_redis_cluster
from senza.components.auto_scaling_group \
    import component_auto_scaling_group, normalize_network_threshold, to_iso8601_duration, normalize_asg_success
from senza.components.taupage_auto_scaling_group import generate_user_data
import senza.traffic


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
    result = component_iam_role(definition, configuration, args, MagicMock(), False, MagicMock())

    assert [{'a': 'b'}] == result['Resources']['MyRole']['Properties']['Policies']


def test_get_merged_policies(monkeypatch):
    role = MagicMock()
    role.policies.all = MagicMock(return_value=[MagicMock(policy_name='pol1', policy_document={'foo': 'bar'})])
    iam = MagicMock()
    iam.Role.return_value = role
    monkeypatch.setattr('boto3.resource', lambda x: iam)
    assert [{'PolicyDocument': {'foo': 'bar'}, 'PolicyName': 'pol1'}] == get_merged_policies(['RoleA'])


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

    result = component_elastic_load_balancer(definition, configuration, args, info, False, MagicMock())
    # Defaults to HTTP
    assert "HTTP:9999/healthcheck" == result["Resources"]["test_lb"]["Properties"]["HealthCheck"]["Target"]

    # Support own health check port
    configuration["HealthCheckPort"] = "1234"
    result = component_elastic_load_balancer(definition, configuration, args, info, False, MagicMock())
    assert "HTTP:1234/healthcheck" == result["Resources"]["test_lb"]["Properties"]["HealthCheck"]["Target"]
    del(configuration["HealthCheckPort"])

    # Supports other AWS protocols
    configuration["HealthCheckProtocol"] = "TCP"
    result = component_elastic_load_balancer(definition, configuration, args, info, False, MagicMock())
    assert "TCP:9999/healthcheck" == result["Resources"]["test_lb"]["Properties"]["HealthCheck"]["Target"]

    # Will fail on incorrect protocol
    configuration["HealthCheckProtocol"] = "MYFANCYPROTOCOL"
    try:
        component_elastic_load_balancer(definition, configuration, args, info, False, MagicMock())
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
    result = component_elastic_load_balancer(definition, configuration, args, info, False, MagicMock())
    assert 300 == result["Resources"]["test_lb"]["Properties"]["ConnectionSettings"]["IdleTimeout"]
    assert 'HTTPPort' not in result["Resources"]["test_lb"]["Properties"]


def test_component_load_balancer_namelength(monkeypatch):
    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        "HealthCheckPath": "/healthcheck"
    }
    info = {'StackName': 'foobar' * 5, 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = "foo"
    monkeypatch.setattr('senza.components.elastic_load_balancer.find_ssl_certificate_arn', mock_string_result)
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    result = component_elastic_load_balancer(definition, configuration, args, info, False, MagicMock())
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
    sn1.tags = [{'Key': 'Name', 'Value': 'dmz-1'}]
    sn1.availability_zone = 'az-1'
    sn2 = MagicMock()
    sn2.id = 'sn-2'
    sn2.tags = [{'Key': 'Name', 'Value': 'dmz-2'}]
    sn2.availability_zone = 'az-2'
    sn3 = MagicMock()
    sn3.id = 'sn-3'
    sn3.tags = [{'Key': 'Name', 'Value': 'internal-3'}]
    sn3.availability_zone = 'az-1'
    ec2 = MagicMock()
    ec2.subnets.filter.return_value = [sn1, sn2, sn3]
    image = MagicMock()
    ec2.images.filter.return_value = [image]
    monkeypatch.setattr('boto3.resource', lambda x, y: ec2)

    result = component_stups_auto_configuration({}, configuration, args, MagicMock(), False, MagicMock())

    assert {'myregion': {'Subnets': ['sn-1']}} == result['Mappings']['LoadBalancerSubnets']
    assert {'myregion': {'Subnets': ['sn-3']}} == result['Mappings']['ServerSubnets']


def test_component_redis_node(monkeypatch):
    mock_string = "foo"

    configuration = {
        "Name": mock_string,
        "SecurityGroups": "",
    }
    info = {'StackName': 'foobar' * 5, 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = mock_string
    monkeypatch.setattr('senza.components.redis_node.resolve_security_groups', mock_string_result)

    result = component_redis_node(definition, configuration, args, info, False, MagicMock())

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
    info = {'StackName': 'foobar' * 5, 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = mock_string
    monkeypatch.setattr('senza.components.redis_cluster.resolve_security_groups', mock_string_result)

    result = component_redis_cluster(definition, configuration, args, info, False, MagicMock())

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


def test_weighted_dns_load_balancer(monkeypatch):
    senza.traffic.DNS_ZONE_CACHE = {}

    def my_client(rtype, *args):
        if rtype == 'route53':
            route53 = MagicMock()
            route53.list_hosted_zones.return_value = {'HostedZones': [{'Id': '/hostedzone/123456',
                                                                       'Name': 'domain.',
                                                                       'ResourceRecordSetCount': 23}],
                                                      'IsTruncated': False,
                                                      'MaxItems': '100'}
            return route53
        return MagicMock()

    monkeypatch.setattr('boto3.client', my_client)

    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        'MainDomain': 'main.domain',
        'VersionDomain': 'version.domain'
    }
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = "foo"
    monkeypatch.setattr('senza.components.elastic_load_balancer.find_ssl_certificate_arn', mock_string_result)
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    result = component_weighted_dns_elastic_load_balancer(definition,
                                                          configuration,
                                                          args,
                                                          info,
                                                          False,
                                                          AccountArguments('dummyregion'))

    assert 'MainDomain' not in result["Resources"]["test_lb"]["Properties"]


def test_weighted_dns_load_balancer_with_different_domains(monkeypatch):
    senza.traffic.DNS_ZONE_CACHE = {}

    def my_client(rtype, *args):
        if rtype == 'route53':
            route53 = MagicMock()
            route53.list_hosted_zones.return_value = {'HostedZones': [{'Id': '/hostedzone/123456',
                                                                       'Name': 'zo.ne.dev.',
                                                                       'ResourceRecordSetCount': 23},
                                                                      {'Id': '/hostedzone/123457',
                                                                       'Name': 'zo.ne.com.',
                                                                       'ResourceRecordSetCount': 23}],
                                                      'IsTruncated': False,
                                                      'MaxItems': '100'}
            return route53
        return MagicMock()

    monkeypatch.setattr('boto3.client', my_client)

    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        'MainDomain': 'great.api.zo.ne.com',
        'VersionDomain': 'version.api.zo.ne.dev'
    }
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = "foo"
    monkeypatch.setattr('senza.components.elastic_load_balancer.find_ssl_certificate_arn', mock_string_result)
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    result = component_weighted_dns_elastic_load_balancer(definition,
                                                          configuration,
                                                          args,
                                                          info,
                                                          False,
                                                          AccountArguments('dummyregion'))

    assert 'zo.ne.com.' == result["Resources"]["test_lbMainDomain"]["Properties"]['HostedZoneName']
    assert 'zo.ne.dev.' == result["Resources"]["test_lbVersionDomain"]["Properties"]['HostedZoneName']

    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        'MainDomain': 'this.does.not.exists.com',
        'VersionDomain': 'this.does.not.exists.com'
    }
    senza.traffic.DNS_ZONE_CACHE = {}
    try:
        result = component_weighted_dns_elastic_load_balancer(definition,
                                                              configuration,
                                                              args,
                                                              info,
                                                              False,
                                                              AccountArguments('dummyregion'))
    except ValueError:
        pass
    except:
        assert False, 'raise unknown exception'
    else:

        print(result)
        print(configuration)
        assert False, 'doesn\'t raise a ValueError exception'


def test_component_taupage_auto_scaling_group_user_data_without_ref():
    configuration = {
        'runtime': 'Docker',
        'environment': {
            'ENV3': "r3"
        }
    }

    expected_user_data = '#taupage-ami-config\nenvironment:\n  ENV3: r3\nruntime: Docker\n'

    assert expected_user_data == generate_user_data(configuration)


def test_component_taupage_auto_scaling_group_user_data_with_ref():
    configuration = {
        'runtime': 'Docker',
        'source': {'Fn::Join': ['/', ['pierone.stups.zalan.do', 'cool', {'Fn::GetAtt': ['Obj1', 'Attr1']}]]},
        'mint_bucket': {'Ref': 'REF1'},
        'environment': {
            'ENV1': {'Fn::GetAtt': ['Obj2', 'Attr2']},
            'ENV2': {'Ref': 'REF2'},
            'ENV3': "r3"
        }
    }

    expected_user_data = {
        'Fn::Join': ['', [
            '#taupage-ami-config\nenvironment:\n  ENV1: ', {'Fn::GetAtt': ['Obj2', 'Attr2']},
            '\n  ENV2: ', {'Ref': 'REF2'}, '\n  ENV3: r3\nmint_bucket: ', {'Ref': 'REF1'},
            '\nruntime: Docker\nsource: ', {'Fn::Join': ['/', ['pierone.stups.zalan.do', 'cool',
                                                         {'Fn::GetAtt': ['Obj1', 'Attr1']}]]}, '\n']]}

    assert expected_user_data == generate_user_data(configuration)


def test_component_taupage_auto_scaling_group_user_data_with_lists_and_empty_dict():
    configuration = {
        'resources': ['A', {"Ref": "Res1"}],
        'ports': {}
    }

    expected_user_data = {'Fn::Join': ['', [
        '#taupage-ami-config\nports: {}\nresources:\n- A\n- ', {'Ref': 'Res1'}, '\n']]}

    assert expected_user_data == generate_user_data(configuration)


def test_component_auto_scaling_group_configurable_properties():
    definition = {"Resources": {}}
    configuration = {
        'Name': 'Foo',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'AutoScaling': {
            'Minimum': 2,
            'Maximum': 10,
            'SuccessRequires': '4 within 30m',
            'MetricType': 'CPU',
            'Period': 60,
            'ScaleUpThreshold': 50,
            'ScaleDownThreshold': 20,
            'EvaluationPeriods': 1,
            'Cooldown': 30,
            'Statistic': 'Maximum'
        }
    }

    args = MagicMock()
    args.region = "foo"

    info = {
        'StackName': 'FooStack',
        'StackVersion': 'FooVersion'
    }

    result = component_auto_scaling_group(definition, configuration, args, info, False, MagicMock())

    assert result["Resources"]["FooScaleUp"] is not None
    assert result["Resources"]["FooScaleUp"]["Properties"] is not None
    assert result["Resources"]["FooScaleUp"]["Properties"]["ScalingAdjustment"] == "1"
    assert result["Resources"]["FooScaleUp"]["Properties"]["Cooldown"] == "30"

    assert result["Resources"]["FooScaleDown"] is not None
    assert result["Resources"]["FooScaleDown"]["Properties"] is not None
    assert result["Resources"]["FooScaleDown"]["Properties"]["Cooldown"] == "30"
    assert result["Resources"]["FooScaleDown"]["Properties"]["ScalingAdjustment"] == "-1"

    assert result["Resources"]["Foo"] is not None

    assert result["Resources"]["Foo"]["CreationPolicy"] is not None
    assert result["Resources"]["Foo"]["CreationPolicy"]["ResourceSignal"] is not None
    assert result["Resources"]["Foo"]["CreationPolicy"]["ResourceSignal"]["Timeout"] == "PT30M"
    assert result["Resources"]["Foo"]["CreationPolicy"]["ResourceSignal"]["Count"] == "4"

    assert result["Resources"]["Foo"]["Properties"] is not None
    assert result["Resources"]["Foo"]["Properties"]["HealthCheckType"] == "EC2"
    assert result["Resources"]["Foo"]["Properties"]["MinSize"] == 2
    assert result["Resources"]["Foo"]["Properties"]["DesiredCapacity"] == 2
    assert result["Resources"]["Foo"]["Properties"]["MaxSize"] == 10

    expected_desc = "Scale-down if CPU < 20% for 1.0 minutes (Maximum)"
    assert result["Resources"]["FooCPUAlarmHigh"]["Properties"]["Statistic"] == "Maximum"
    assert result["Resources"]["FooCPUAlarmLow"]["Properties"]["Period"] == "60"
    assert result["Resources"]["FooCPUAlarmHigh"]["Properties"]["EvaluationPeriods"] == "1"
    assert result["Resources"]["FooCPUAlarmLow"]["Properties"]["AlarmDescription"] == expected_desc


def test_component_auto_scaling_group_metric_type():
    definition = {"Resources": {}}
    configuration = {
        'Name': 'Foo',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'AutoScaling': {
            'Minimum': 2,
            'Maximum': 10,
            'MetricType': 'NetworkIn',
            'Period': 60,
            'EvaluationPeriods': 10,
            'ScaleUpThreshold': '50 TB',
            'ScaleDownThreshold': '10',
            'Statistic': 'Maximum'
        }
    }

    args = MagicMock()
    args.region = "foo"

    info = {
        'StackName': 'FooStack',
        'StackVersion': 'FooVersion'
    }

    result = component_auto_scaling_group(definition, configuration, args, info, False, MagicMock())

    expected_high_desc = "Scale-up if NetworkIn > 50 Terabytes for 10.0 minutes (Maximum)"
    assert result["Resources"]["FooNetworkAlarmHigh"] is not None
    assert result["Resources"]["FooNetworkAlarmHigh"]["Properties"] is not None
    assert result["Resources"]["FooNetworkAlarmHigh"]["Properties"]["MetricName"] == "NetworkIn"
    assert result["Resources"]["FooNetworkAlarmHigh"]["Properties"]["Unit"] == "Terabytes"
    assert result["Resources"]["FooNetworkAlarmHigh"]["Properties"]["Threshold"] == "50"
    assert result["Resources"]["FooNetworkAlarmHigh"]["Properties"]["Statistic"] == "Maximum"
    assert result["Resources"]["FooNetworkAlarmHigh"]["Properties"]["Period"] == "60"
    assert result["Resources"]["FooNetworkAlarmHigh"]["Properties"]["EvaluationPeriods"] == "10"
    assert result["Resources"]["FooNetworkAlarmHigh"]["Properties"]["AlarmDescription"] == expected_high_desc

    expected_low_desc = "Scale-down if NetworkIn < 10 Bytes for 10.0 minutes (Maximum)"
    assert result["Resources"]["FooNetworkAlarmLow"]is not None
    assert result["Resources"]["FooNetworkAlarmLow"]["Properties"] is not None
    assert result["Resources"]["FooNetworkAlarmLow"]["Properties"]["MetricName"] == "NetworkIn"
    assert result["Resources"]["FooNetworkAlarmLow"]["Properties"]["Unit"] == "Bytes"
    assert result["Resources"]["FooNetworkAlarmLow"]["Properties"]["Threshold"] == "10"
    assert result["Resources"]["FooNetworkAlarmLow"]["Properties"]["Statistic"] == "Maximum"
    assert result["Resources"]["FooNetworkAlarmLow"]["Properties"]["Period"] == "60"
    assert result["Resources"]["FooNetworkAlarmLow"]["Properties"]["EvaluationPeriods"] == "10"
    assert result["Resources"]["FooNetworkAlarmLow"]["Properties"]["AlarmDescription"] == expected_low_desc


def test_to_iso8601_duration():
    with pytest.raises(click.UsageError):
        to_iso8601_duration("")

    with pytest.raises(click.UsageError):
        to_iso8601_duration(None)

    with pytest.raises(click.UsageError):
        to_iso8601_duration("foo")

    with pytest.raises(click.UsageError):
        to_iso8601_duration("5s16h")

    assert to_iso8601_duration("5m") == "PT5M"
    assert to_iso8601_duration("5H4s") == "PT5H4S"


def test_normalize_asg_success():
    default = "PT15M"
    assert normalize_asg_success(10) == ["10", default]
    assert normalize_asg_success("10") == ["10", default]
    assert normalize_asg_success("1 within 4h5s") == ["1", "PT4H5S"]
    assert normalize_asg_success("4 within 30m") == ["4", "PT30M"]
    assert normalize_asg_success("1 within 4h0m5s") == ["1", "PT4H0M5S"]
    assert normalize_asg_success("-1 within 5s") == ["-1", "PT5S"]  # i just don't care about this

    with pytest.raises(click.UsageError):
        # no within keyword
        normalize_asg_success("1 in 5m")

    with pytest.raises(click.UsageError):
        # unparseable duration
        normalize_asg_success("1 within 5y")

    with pytest.raises(click.UsageError):
        # duration in wrong order
        normalize_asg_success("1 within 5s4h")


def test_normalize_network_threshold():
    assert normalize_network_threshold(None) == []
    assert normalize_network_threshold("10") == ["10", "Bytes"]
    assert normalize_network_threshold(10) == ["10", "Bytes"]
    assert normalize_network_threshold("10   Gigabytes") == ["10", "Gigabytes"]
    assert normalize_network_threshold("10 B") == ["10", "Bytes"]
    assert normalize_network_threshold("10 KB") == ["10", "Kilobytes"]
    assert normalize_network_threshold("10 MB") == ["10", "Megabytes"]
    assert normalize_network_threshold("10 GB") == ["10", "Gigabytes"]
    assert normalize_network_threshold("5.7 TB") == ["5.7", "Terabytes"]

    with pytest.raises(click.UsageError):
        normalize_network_threshold("5.7GB")

    with pytest.raises(click.UsageError):
        normalize_network_threshold("5 Donkeys")
