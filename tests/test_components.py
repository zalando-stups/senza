from unittest.mock import MagicMock, patch

import click
import pierone.api
import pytest
import senza.traffic
from senza.definitions import AccountArguments
from senza.components import get_component
from senza.components.configuration import component_configuration
from senza.components.auto_scaling_group import (component_auto_scaling_group,
                                                 normalize_asg_success,
                                                 normalize_network_threshold,
                                                 to_iso8601_duration)
from senza.components.coreos_auto_configuration import component_coreos_auto_configuration
from senza.components.elastic_load_balancer import (component_elastic_load_balancer,
                                                    get_load_balancer_name)
from senza.components.elastic_load_balancer_v2 import component_elastic_load_balancer_v2
from senza.components.iam_role import component_iam_role, get_merged_policies
from senza.components.redis_cluster import component_redis_cluster
from senza.components.redis_node import component_redis_node
from senza.components.stups_auto_configuration import \
    component_stups_auto_configuration
from senza.components.subnet_auto_configuration import component_subnet_auto_configuration
from senza.components.taupage_auto_scaling_group import (check_application_id,
                                                         check_application_version,
                                                         check_docker_image_exists,
                                                         generate_user_data)
from senza.components.weighted_dns_elastic_load_balancer import \
    component_weighted_dns_elastic_load_balancer
from senza.components.weighted_dns_elastic_load_balancer_v2 import \
    component_weighted_dns_elastic_load_balancer_v2

from fixtures import (HOSTED_ZONE_ZO_NE_COM, HOSTED_ZONE_ZO_NE_DEV,  # noqa: F401
                      boto_resource, boto_client)


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
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    m_acm = MagicMock()
    m_acm_certificate = MagicMock()
    m_acm_certificate.arn = "foo"
    m_acm.get_certificates.return_value = iter([m_acm_certificate])
    monkeypatch.setattr('senza.components.elastic_load_balancer.ACM', m_acm)

    result = component_elastic_load_balancer(definition, configuration, args, info, False, MagicMock())
    # Defaults to HTTP
    assert "HTTP:9999/healthcheck" == result["Resources"]["test_lb"]["Properties"]["HealthCheck"]["Target"]

    # Support own health check port
    m_acm.get_certificates.return_value = iter([m_acm_certificate])
    configuration["HealthCheckPort"] = "1234"
    result = component_elastic_load_balancer(definition, configuration, args, info, False, MagicMock())
    assert "HTTP:1234/healthcheck" == result["Resources"]["test_lb"]["Properties"]["HealthCheck"]["Target"]
    del(configuration["HealthCheckPort"])

    # Supports other AWS protocols
    m_acm.get_certificates.return_value = iter([m_acm_certificate])
    configuration["HealthCheckProtocol"] = "TCP"
    result = component_elastic_load_balancer(definition, configuration, args, info, False, MagicMock())
    assert "TCP:9999" == result["Resources"]["test_lb"]["Properties"]["HealthCheck"]["Target"]

    # Will fail on incorrect protocol
    m_acm.get_certificates.return_value = iter([m_acm_certificate])
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
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    m_acm = MagicMock()
    m_acm_certificate = MagicMock()
    m_acm_certificate.arn = "foo"
    m_acm.get_certificates.return_value = iter([m_acm_certificate])
    monkeypatch.setattr('senza.components.elastic_load_balancer.ACM', m_acm)

    # issue 105: support additional ELB properties
    result = component_elastic_load_balancer(definition, configuration, args, info, False, MagicMock())
    assert 300 == result["Resources"]["test_lb"]["Properties"]["ConnectionSettings"]["IdleTimeout"]
    assert 'HTTPPort' not in result["Resources"]["test_lb"]["Properties"]


def test_component_load_balancer_cert_arn(monkeypatch):
    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        "SSLCertificateId": "foo2"
    }

    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = "foo"
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    m_acm = MagicMock()
    m_acm_certificate = MagicMock()
    m_acm_certificate.arn = "foo"

    m_acm.get_certificates.return_value = iter([m_acm_certificate])

    m_acm_certificate.is_arn_certificate.return_value = True
    m_acm_certificate.get_by_arn.return_value = True

    monkeypatch.setattr('senza.components.elastic_load_balancer.ACM', m_acm)
    monkeypatch.setattr('senza.components.elastic_load_balancer.ACMCertificate', m_acm_certificate)

    # issue 105: support additional ELB properties
    result = component_elastic_load_balancer(definition, configuration, args, info, False, MagicMock())
    assert "foo2" == result["Resources"]["test_lb"]["Properties"]["Listeners"][0]["SSLCertificateId"]


def test_component_load_balancer_http_only(monkeypatch):
    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        "SSLCertificateId": "arn:none",  # should be ignored as we overwrite Listeners
        "Listeners": [{"Foo": "Bar"}]
    }
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = "foo"
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    result = component_elastic_load_balancer(definition, configuration, args, info, False, MagicMock())
    assert 'Bar' == result["Resources"]["test_lb"]["Properties"]["Listeners"][0]["Foo"]


def test_component_load_balancer_listeners_ssl(monkeypatch):
    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        "Listeners": [{"Protocol": "SSL"}]
    }
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = "foo"
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    get_ssl_cert = MagicMock()
    get_ssl_cert.return_value = 'my-ssl-arn'
    monkeypatch.setattr('senza.components.elastic_load_balancer.get_ssl_cert', get_ssl_cert)

    result = component_elastic_load_balancer(definition, configuration, args, info, False, MagicMock())
    assert 'my-ssl-arn' == result["Resources"]["test_lb"]["Properties"]["Listeners"][0]["SSLCertificateId"]


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
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    m_acm = MagicMock()
    m_acm_certificate = MagicMock()
    m_acm_certificate.arn = "foo"
    m_acm.get_certificates.return_value = iter([m_acm_certificate])
    monkeypatch.setattr('senza.components.elastic_load_balancer.ACM', m_acm)

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


def test_component_stups_auto_configuration_vpc_id(monkeypatch):
    args = MagicMock()
    args.region = 'myregion'

    configuration = {
        'Name': 'Config',
        'VpcId': 'vpc-123'
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

    def get_subnets(Filters):
        assert Filters == [{'Name': 'vpc-id', 'Values': ['vpc-123']}]
        return [sn1, sn2, sn3]

    ec2.subnets.filter = get_subnets
    image = MagicMock()
    ec2.images.filter.return_value = [image]
    monkeypatch.setattr('boto3.resource', lambda x, y: ec2)

    result = component_stups_auto_configuration({}, configuration, args, MagicMock(), False, MagicMock())

    assert {'myregion': {'Subnets': ['sn-1', 'sn-2']}} == result['Mappings']['LoadBalancerSubnets']
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
    assert result['Resources']['RedisReplicationGroup']['Properties']['AutomaticFailoverEnabled']
    assert 'Engine' in result['Resources']['RedisReplicationGroup']['Properties']
    assert 'EngineVersion' in result['Resources']['RedisReplicationGroup']['Properties']
    assert 'CacheNodeType' in result['Resources']['RedisReplicationGroup']['Properties']
    assert 'CacheSubnetGroupName' in result['Resources']['RedisReplicationGroup']['Properties']
    assert 'CacheParameterGroupName' in result['Resources']['RedisReplicationGroup']['Properties']

    assert 'RedisSubnetGroup' in result['Resources']
    assert 'SubnetIds' in result['Resources']['RedisSubnetGroup']['Properties']


def test_weighted_dns_load_balancer(monkeypatch, boto_client, boto_resource):  # noqa: F811
    senza.traffic.DNS_ZONE_CACHE = {}

    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        'MainDomain': 'great.api.zo.ne',
        'VersionDomain': 'version.api.zo.ne'
    }
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = "foo"
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    m_acm = MagicMock()
    m_acm_certificate = MagicMock()
    m_acm_certificate.arn = "foo"
    m_acm.get_certificates.return_value = iter([m_acm_certificate])
    monkeypatch.setattr('senza.components.elastic_load_balancer.ACM', m_acm)

    result = component_weighted_dns_elastic_load_balancer(definition,
                                                          configuration,
                                                          args,
                                                          info,
                                                          False,
                                                          AccountArguments('dummyregion'))

    assert 'MainDomain' not in result["Resources"]["test_lb"]["Properties"]


def test_weighted_dns_load_balancer_with_different_domains(monkeypatch,  # noqa: F811
                                                           boto_client,
                                                           boto_resource):
    senza.traffic.DNS_ZONE_CACHE = {}

    boto_client['route53'].list_hosted_zones.return_value = {
        'HostedZones': [HOSTED_ZONE_ZO_NE_DEV,
                        HOSTED_ZONE_ZO_NE_COM],
        'IsTruncated': False,
        'MaxItems': '100'}

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
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    m_acm = MagicMock()
    m_acm_certificate = MagicMock()
    m_acm_certificate.arn = "foo"
    m_acm.get_certificates.return_value = iter([m_acm_certificate])
    monkeypatch.setattr('senza.components.elastic_load_balancer.ACM', m_acm)

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
    with pytest.raises(AttributeError):
        result = component_weighted_dns_elastic_load_balancer(definition,
                                                              configuration,
                                                              args,
                                                              info,
                                                              False,
                                                              AccountArguments('dummyregion'))


def test_component_taupage_auto_scaling_group_user_data_without_ref():
    configuration = {
        'runtime': 'Docker',
        'environment': {
            'ENV3': "r3"
        }
    }

    expected_user_data = '#taupage-ami-config\nenvironment:\n  ENV3: r3\nruntime: Docker\n'

    assert expected_user_data == generate_user_data(configuration, 'region')


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

    assert expected_user_data == generate_user_data(configuration, 'region')


def test_component_taupage_auto_scaling_group_user_data_with_lists_and_empty_dict():
    configuration = {
        'resources': ['A', {"Ref": "Res1"}],
        'ports': {}
    }

    expected_user_data = {'Fn::Join': ['', [
        '#taupage-ami-config\nports: {}\nresources:\n- A\n- ', {'Ref': 'Res1'}, '\n']]}

    assert expected_user_data == generate_user_data(configuration, 'region')


def test_component_auto_scaling_group_configurable_properties():
    definition = {"Resources": {}}
    configuration = {
        'Name': 'Foo',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'MetricsCollection': {'Granularity': '1Minute'},
        'AutoScaling': {
            'Minimum': 2,
            'Maximum': 10,
            'SuccessRequires': '4 within 30m',
            'MetricType': 'CPU',
            'Period': 60,
            'ScaleUpThreshold': 50,
            'ScaleDownThreshold': 20,
            'EvaluationPeriods': 1,
            'ScalingAdjustment': 1,
            'ScaleUpAdjustment': 3,
            'Cooldown': 30,
            'ScaleDownCooldown': 360,
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
    assert result["Resources"]["FooScaleUp"]["Properties"]["ScalingAdjustment"] == "3"
    assert result["Resources"]["FooScaleUp"]["Properties"]["Cooldown"] == "30"

    assert result["Resources"]["FooScaleDown"] is not None
    assert result["Resources"]["FooScaleDown"]["Properties"] is not None
    assert result["Resources"]["FooScaleDown"]["Properties"]["Cooldown"] == "360"
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
    assert result['Resources']['Foo']['Properties']['MetricsCollection'] == {'Granularity': '1Minute'}

    expected_desc = "Scale-down if CPU < 20% for 1.0 minutes (Maximum)"
    assert result["Resources"]["FooCPUAlarmHigh"]["Properties"]["Statistic"] == "Maximum"
    assert result["Resources"]["FooCPUAlarmLow"]["Properties"]["Period"] == "60"
    assert result["Resources"]["FooCPUAlarmHigh"]["Properties"]["EvaluationPeriods"] == "1"
    assert result["Resources"]["FooCPUAlarmLow"]["Properties"]["AlarmDescription"] == expected_desc


def test_component_auto_scaling_group_custom_tags():
    definition = {"Resources": {}}
    configuration = {
        'Name': 'Foo',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'Tags': [
            {'Key': 'Tag1', 'Value': 'alpha'},
            {'Key': 'Tag2', 'Value': 'beta'}
        ]
    }

    args = MagicMock()
    args.region = "foo"

    info = {
        'StackName': 'FooStack',
        'StackVersion': 'FooVersion'
    }

    result = component_auto_scaling_group(definition, configuration, args, info, False, MagicMock())

    assert result["Resources"]["Foo"] is not None
    assert result["Resources"]["Foo"]["Properties"] is not None
    assert result["Resources"]["Foo"]["Properties"]["Tags"] is not None
    # verify custom tags:
    t1 = next(t for t in result["Resources"]["Foo"]["Properties"]["Tags"] if t["Key"] == 'Tag1')
    assert t1 is not None
    assert t1["Value"] == 'alpha'
    t2 = next(t for t in result["Resources"]["Foo"]["Properties"]["Tags"] if t["Key"] == 'Tag2')
    assert t2 is not None
    assert t2["Value"] == 'beta'
    # verify default tags are in place:
    ts = next(t for t in result["Resources"]["Foo"]["Properties"]["Tags"] if t["Key"] == 'Name')
    assert ts is not None
    assert ts["Value"] == 'FooStack-FooVersion'


def test_component_auto_scaling_group_configurable_properties2():
    definition = {"Resources": {}}
    configuration = {
        'Name': 'Foo',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'SpotPrice': 0.250
    }

    args = MagicMock()
    args.region = "foo"

    info = {
        'StackName': 'FooStack',
        'StackVersion': 'FooVersion'
    }

    result = component_auto_scaling_group(definition, configuration, args, info, False, MagicMock())

    assert result["Resources"]["FooConfig"]["Properties"]["SpotPrice"] == 0.250

    del configuration["SpotPrice"]

    result = component_auto_scaling_group(definition, configuration, args, info, False, MagicMock())

    assert "SpotPrice" not in result["Resources"]["FooConfig"]["Properties"]


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


def test_component_auto_scaling_group_optional_metric_type():
    definition = {"Resources": {}}
    configuration = {
        'Name': 'Foo',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'AutoScaling': {
            'Minimum': 2,
            'Maximum': 10,
        }
    }

    args = MagicMock()
    args.region = "foo"

    info = {
        'StackName': 'FooStack',
        'StackVersion': 'FooVersion'
    }

    result = component_auto_scaling_group(definition, configuration, args, info, False, MagicMock())

    assert "FooCPUAlarmHigh" not in result["Resources"]
    assert "FooNetworkAlarmHigh" not in result["Resources"]


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


def test_check_docker_image_exists():
    def build_image(from_registry_url: str):
        return pierone.api.DockerImage(registry=from_registry_url,
                                       team='bar', artifact='foobar',
                                       tag='1.0')

    pierone_has_cves = {
        'tag': '1.0',
        'team': 'foo',
        'artifact': 'app1',
        'severity_fix_available': 'HIGH',
        'severity_no_fix_available': 'LOW',
        'created_by': 'myuser',
        'created': '2015-08-01T08:14:59.432Z'
    }

    pierone_no_cves = {
        'tag': '2.0',
        'team': 'foo',
        'artifact': 'app1',
        'severity_fix_available': 'NO_CVES_FOUND',
        'severity_no_fix_available': 'NO_CVES_FOUND',
        'created_by': 'myuser',
        'created': '2016-06-20T08:14:59.432Z'
    }

    fake_token = {
        'access_token': 'abc'
    }

    # image from pierone has CVEs
    with patch('senza.components.taupage_auto_scaling_group.click.secho') as output_function, patch(
            "senza.components.taupage_auto_scaling_group.get_token",
            return_value=fake_token), patch(
            'senza.components.taupage_auto_scaling_group.pierone.api.image_exists',
            return_value=True), patch(
                'senza.components.taupage_auto_scaling_group.pierone.api.get_image_tag',
                return_value=pierone_has_cves):

        check_docker_image_exists(build_image(from_registry_url='pierone'))

        assert output_function.called
        assert 'Please check this artifact tag in pierone' in output_function.call_args[0][0]

    # image from pierone no CVEs
    with patch('senza.components.taupage_auto_scaling_group.click.secho') as output_function, patch(
            "senza.components.taupage_auto_scaling_group.get_token",
            return_value=fake_token), patch(
            'senza.components.taupage_auto_scaling_group.pierone.api.image_exists',
            return_value=True), patch(
                'senza.components.taupage_auto_scaling_group.pierone.api.get_image_tag',
                return_value=pierone_no_cves):

        check_docker_image_exists(build_image(from_registry_url='pierone'))

        assert not output_function.called

    # image from pierone auth error
    with patch("senza.components.taupage_auto_scaling_group.get_token",
               return_value=None), pytest.raises(click.UsageError):

        check_docker_image_exists(build_image(from_registry_url='pierone'))

    # image from pierone and not 'pierone' in url has CVEs
    with patch('senza.components.taupage_auto_scaling_group.click.secho') as output_function, patch(
            'senza.components.taupage_auto_scaling_group.docker_image_exists',
            return_value=True), patch(
                'senza.components.taupage_auto_scaling_group.pierone.api.get_image_tag',
                return_value=pierone_has_cves):

        check_docker_image_exists(build_image(from_registry_url='opensource'))

        assert output_function.called
        assert 'Please check this artifact tag in pierone' in output_function.call_args[0][0]

    # image from pierone and not 'pierone' in url no CVEs
    with patch('senza.components.taupage_auto_scaling_group.click.secho') as output_function, patch(
            'senza.components.taupage_auto_scaling_group.docker_image_exists',
            return_value=True), patch(
                'senza.components.taupage_auto_scaling_group.pierone.api.get_image_tag',
                return_value=pierone_no_cves):

        check_docker_image_exists(build_image(from_registry_url='opensource'))

        assert not output_function.called

    # image from dockerhub
    with patch('senza.components.taupage_auto_scaling_group.click.secho') as output_function, patch(
            'senza.components.taupage_auto_scaling_group.docker_image_exists',
            return_value=True), patch(
                'senza.components.taupage_auto_scaling_group.pierone.api.get_image_tag',
                return_value=None):

        check_docker_image_exists(build_image(from_registry_url='opensource'))

        assert output_function.called
        assert 'not automatically checked' in output_function.call_args[0][0]


def test_check_application_id():
    check_application_id('test-app')

    check_application_id('myapp')

    with pytest.raises(click.UsageError):
        check_application_id('42yolo')

    with pytest.raises(click.UsageError):
        check_application_id('test-APP')


def test_check_application_version():
    check_application_version('1.0')

    check_application_version('MyVersion')

    with pytest.raises(click.UsageError):
        check_application_id('.1')

    with pytest.raises(click.UsageError):
        check_application_id('1.')


def test_get_load_balancer_name():
    get_load_balancer_name('a', '1') == 'a-1'

    get_load_balancer_name('toolong123456789012345678901234567890',
                           '1') == 'toolong12345678901234567890123-1'


def test_weighted_dns_load_balancer_v2_no_certificate(monkeypatch, boto_client, boto_resource):  # noqa: F811
    senza.traffic.DNS_ZONE_CACHE = {}

    configuration = {
        "Name": "MyLB",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        'MainDomain': 'great.api.zo.ne',
        'VersionDomain': 'version.api.zo.ne',
        # test overwritting specific properties in one of the resources
        'TargetGroupAttributes': [{'Key': 'deregistration_delay.timeout_seconds', 'Value': '123'}],
        # test that Security Groups are resolved
        'SecurityGroups': ['foo-security-group']
    }
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = ['sg-foo']
    monkeypatch.setattr('senza.components.elastic_load_balancer_v2.resolve_security_groups', mock_string_result)

    get_ssl_cert = MagicMock()
    get_ssl_cert.return_value = 'arn:aws:42'
    monkeypatch.setattr('senza.components.elastic_load_balancer_v2.get_ssl_cert', get_ssl_cert)

    result = component_weighted_dns_elastic_load_balancer_v2(definition,
                                                             configuration,
                                                             args,
                                                             info,
                                                             False,
                                                             AccountArguments('dummyregion'))

    assert 'MyLB' in result["Resources"]
    assert 'MyLBListener' in result["Resources"]
    assert 'MyLBTargetGroup' in result["Resources"]

    target_group = result['Resources']['MyLBTargetGroup']
    lb_listener = result['Resources']['MyLBListener']

    assert target_group['Properties']['HealthCheckPort'] == '9999'
    assert lb_listener['Properties']['Certificates'] == [
        {'CertificateArn': 'arn:aws:42'}
    ]
    # test that our custom drain setting works
    assert target_group['Properties']['TargetGroupAttributes'] == [
        {'Key': 'deregistration_delay.timeout_seconds',
         'Value': '123'}
    ]
    assert result['Resources']['MyLB']['Properties']['SecurityGroups'] == ['sg-foo']


def test_weighted_dns_load_balancer_v2_two_certificates(monkeypatch, boto_client, boto_resource):  # noqa: F811
    senza.traffic.DNS_ZONE_CACHE = {}

    configuration = {
        "Name": "MyLB",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        'MainDomain': 'great.api.zo.ne',
        'SSLCertificateId': 'my-cert,my-other-cert',
        'VersionDomain': 'version.api.zo.ne',
        # test overwritting specific properties in one of the resources
        'TargetGroupAttributes': [{'Key': 'deregistration_delay.timeout_seconds', 'Value': '123'}],
        # test that Security Groups are resolved
        'SecurityGroups': ['foo-security-group']
    }
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = ['sg-foo']
    monkeypatch.setattr('senza.components.elastic_load_balancer_v2.resolve_security_groups', mock_string_result)

    get_ssl_cert = MagicMock()
    get_ssl_cert.side_effect = ['arn:aws:42', 'arn:aws:13']
    monkeypatch.setattr('senza.components.elastic_load_balancer_v2.get_ssl_cert', get_ssl_cert)

    result = component_weighted_dns_elastic_load_balancer_v2(definition,
                                                             configuration,
                                                             args,
                                                             info,
                                                             False,
                                                             AccountArguments('dummyregion'))

    assert 'MyLB' in result["Resources"]
    assert 'MyLBListener' in result["Resources"]
    assert 'MyLBTargetGroup' in result["Resources"]

    target_group = result['Resources']['MyLBTargetGroup']
    lb_listener = result['Resources']['MyLBListener']

    assert target_group['Properties']['HealthCheckPort'] == '9999'
    assert lb_listener['Properties']['Certificates'] == [
        {'CertificateArn': 'arn:aws:42'},
        {'CertificateArn': 'arn:aws:13'}
    ]
    # test that our custom drain setting works
    assert target_group['Properties']['TargetGroupAttributes'] == [
        {'Key': 'deregistration_delay.timeout_seconds',
         'Value': '123'}
    ]
    assert result['Resources']['MyLB']['Properties']['SecurityGroups'] == ['sg-foo']


def test_max_description_length():
    definition = {}
    configuration = {}
    args = MagicMock()
    args.__dict__ = {'Param1': 'my param value', 'SecondParam': ('1234567890' * 100)}
    info = {'StackName': 'My-Stack'}
    component_configuration(definition, configuration, args, info, False, AccountArguments('dummyregion'))
    assert definition['Description'].startswith('My Stack (Param1: my param value, SecondParam: 1234567890')
    assert 0 < len(definition['Description']) <= 1024


def test_template_parameters():
    definition = {}
    configuration = {'DefineParameters': False}
    args = MagicMock()
    args.__dict__ = {'Param1': 'my param value', 'SecondParam': ('1234567890' * 100)}
    info = {'StackName': 'My-Stack', 'Parameters': []}
    component_configuration(definition, configuration, args, info, False, AccountArguments('dummyregion'))
    assert definition.get('Parameters') == None


def test_component_load_balancer_default_internal_scheme(monkeypatch):
    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999"
    }
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = "foo"
    monkeypatch.setattr('senza.components.elastic_load_balancer.resolve_security_groups', mock_string_result)

    result = component_elastic_load_balancer(definition, configuration, args, info, False, MagicMock())
    assert 'internal' == result["Resources"]["test_lb"]["Properties"]["Scheme"]


def test_component_load_balancer_v2_default_internal_scheme(monkeypatch):
    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999"
    }
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = "foo"
    monkeypatch.setattr('senza.components.elastic_load_balancer_v2.resolve_security_groups', mock_string_result)

    result = component_elastic_load_balancer_v2(definition, configuration, args, info, False, MagicMock())
    assert 'internal' == result["Resources"]["test_lb"]["Properties"]["Scheme"]


def test_component_load_balancer_v2_target_group_vpc_id(monkeypatch):
    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        "VpcId": "0a-12345"
    }
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    mock_string_result = MagicMock()
    mock_string_result.return_value = "foo"
    monkeypatch.setattr('senza.components.elastic_load_balancer_v2.resolve_security_groups', mock_string_result)

    result = component_elastic_load_balancer_v2(definition, configuration, args, info, False, MagicMock())
    assert '0a-12345' == result["Resources"]["test_lbTargetGroup"]["Properties"]["VpcId"]


def test_component_subnet_auto_configuration(monkeypatch):
    configuration = {
        'PublicOnly': True,
        'VpcId': 'vpc-123'
    }
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    subnet1 = MagicMock()
    subnet1.id = 'subnet-1'
    subnet2 = MagicMock()
    subnet2.id = 'subnet-2'

    ec2 = MagicMock()
    ec2.subnets.filter.return_value = [subnet1, subnet2]
    monkeypatch.setattr('boto3.resource', lambda *args: ec2)

    result = component_subnet_auto_configuration(definition, configuration, args, info, False, MagicMock())
    assert ['subnet-1', 'subnet-2'] == result['Mappings']['ServerSubnets']['foo']['Subnets']

    configuration = {
        'PublicOnly': False,
        'VpcId': 'vpc-123'
    }
    result = component_subnet_auto_configuration(definition, configuration, args, info, False, MagicMock())
    assert ['subnet-1', 'subnet-2'] == result['Mappings']['ServerSubnets']['foo']['Subnets']


def test_component_coreos_auto_configuration(monkeypatch):
    configuration = {
        'ReleaseChannel': 'gamma'
    }
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    definition = {"Resources": {}}

    args = MagicMock()
    args.region = "foo"

    subnet1 = MagicMock()
    subnet1.id = 'subnet-1'

    ec2 = MagicMock()
    ec2.subnets.filter.return_value = [subnet1]

    get = MagicMock()
    get.return_value.json.return_value = {'foo': {'hvm': 'ami-007'}}

    monkeypatch.setattr('boto3.resource', lambda *args: ec2)
    monkeypatch.setattr('requests.get', get)
    result = component_coreos_auto_configuration(definition, configuration, args, info, False, MagicMock())
    assert 'ami-007' == result['Mappings']['Images']['foo']['LatestCoreOSImage']

def test_component_autoscaling_group_single_string_load_balancer(monkeypatch):
    configuration = {
        'Name': 'Test',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'ElasticLoadBalancer': 'LB1'
    }
    definition = {"Resources": {}}
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    args = MagicMock()
    args.region = "foo"

    result = component_auto_scaling_group(definition, configuration, args, info, False, MagicMock())

    assert [{'Ref': 'LB1'}] == result['Resources']['Test']['Properties']['LoadBalancerNames']

def test_component_autoscaling_group_single_list_load_balancer(monkeypatch):
    configuration = {
        'Name': 'Test',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'ElasticLoadBalancer': [ 'LB1' ]
    }
    definition = {"Resources": {}}
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    args = MagicMock()
    args.region = "foo"

    result = component_auto_scaling_group(definition, configuration, args, info, False, MagicMock())

    assert [{'Ref': 'LB1'}] == result['Resources']['Test']['Properties']['LoadBalancerNames']

def test_component_autoscaling_group_multiple_load_balancer(monkeypatch):
    configuration = {
        'Name': 'Test',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'ElasticLoadBalancer': [ 'LB1', 'LB2' ]
    }
    definition = {"Resources": {}}
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    args = MagicMock()
    args.region = "foo"

    result = component_auto_scaling_group(definition, configuration, args, info, False, MagicMock())

    assert [{'Ref': 'LB1'},{'Ref': 'LB2'}] == result['Resources']['Test']['Properties']['LoadBalancerNames']

def test_component_autoscaling_group_single_string_load_balancer_v2(monkeypatch):
    configuration = {
        'Name': 'Test',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'ElasticLoadBalancerV2': 'LB1'
    }
    definition = {"Resources": {}}
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    args = MagicMock()
    args.region = "foo"

    result = component_auto_scaling_group(definition, configuration, args, info, False, MagicMock())

    assert [{'Ref': 'LB1TargetGroup'}] == result['Resources']['Test']['Properties']['TargetGroupARNs']

def test_component_autoscaling_group_single_list_load_balancer_v2(monkeypatch):
    configuration = {
        'Name': 'Test',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'ElasticLoadBalancerV2': [ 'LB1' ]
    }
    definition = {"Resources": {}}
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    args = MagicMock()
    args.region = "foo"

    result = component_auto_scaling_group(definition, configuration, args, info, False, MagicMock())

    assert [{'Ref': 'LB1TargetGroup'}] == result['Resources']['Test']['Properties']['TargetGroupARNs']

def test_component_autoscaling_group_multiple_load_balancer_v2(monkeypatch):
    configuration = {
        'Name': 'Test',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'ElasticLoadBalancerV2': [ 'LB1', 'LB2']
    }
    definition = {"Resources": {}}
    info = {'StackName': 'foobar', 'StackVersion': '0.1'}
    args = MagicMock()
    args.region = "foo"

    result = component_auto_scaling_group(definition, configuration, args, info, False, MagicMock())

    assert [{'Ref': 'LB1TargetGroup'},{'Ref': 'LB2TargetGroup'}] == result['Resources']['Test']['Properties']['TargetGroupARNs']
