from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from senza.manaus.elb import ELB
from senza.manaus.exceptions import ELBNotFound


def test_get_hosted_zone(monkeypatch):
    m_client = MagicMock()
    m_client.return_value = m_client
    description1 = {'AvailabilityZones': ['eu-central-1a', 'eu-central-1b'],
                    'BackendServerDescriptions': [],
                    'CanonicalHostedZoneName': 'example.eu-central-1.elb.amazonaws.com',
                    'CanonicalHostedZoneNameID': 'Z215JYRZR1TBD5',
                    'CreatedTime': datetime(2016, 6, 30,
                                            8, 56, 37, 260000,
                                            tzinfo=timezone.utc),
                    'DNSName': 'example.eu-central-1.elb.amazonaws.com',
                    'HealthCheck': {'HealthyThreshold': 2,
                                    'Interval': 10,
                                    'Target': 'HTTP:8080/health_check',
                                    'Timeout': 5,
                                    'UnhealthyThreshold': 2},
                    'Instances': [{'InstanceId': 'i-0000'}],
                    'ListenerDescriptions': [
                        {'Listener': {'InstancePort': 8080,
                                      'InstanceProtocol': 'HTTP',
                                      'LoadBalancerPort': 443,
                                      'Protocol': 'HTTPS',
                                      'SSLCertificateId': 'arn:aws:iam::000:server-certificate/cert'},
                         'PolicyNames': ['ELBSecurityPolicy-2015-05']}],
                    'LoadBalancerName': 'example-2',
                    'Policies': {'AppCookieStickinessPolicies': [],
                                 'LBCookieStickinessPolicies': [],
                                 'OtherPolicies': [
                                     'ELBSecurityPolicy-2015-05']},
                    'Scheme': 'internet-facing',
                    'SecurityGroups': ['sg-a97d82c1'],
                    'SourceSecurityGroup': {'GroupName': 'app-example-lb',
                                            'OwnerAlias': '000'},
                    'Subnets': ['subnet-0000', 'subnet-0000'],
                    'VPCId': 'vpc-0000'}

    description2 = {'AvailabilityZones': ['eu-central-1a', 'eu-central-1b'],
                    'BackendServerDescriptions': [],
                    'CanonicalHostedZoneName': 'test.eu-central-1.elb.amazonaws.com',
                    'CanonicalHostedZoneNameID': 'ABCDWRONG',
                    'CreatedTime': datetime(2016, 6, 30,
                                            8, 56, 37, 260000,
                                            tzinfo=timezone.utc),
                    'DNSName': 'test.eu-central-1.elb.amazonaws.com',
                    'HealthCheck': {'HealthyThreshold': 2,
                                    'Interval': 10,
                                    'Target': 'HTTP:8080/health_check',
                                    'Timeout': 5,
                                    'UnhealthyThreshold': 2},
                    'Instances': [{'InstanceId': 'i-0000'}],
                    'ListenerDescriptions': [
                        {'Listener': {'InstancePort': 8080,
                                      'InstanceProtocol': 'HTTP',
                                      'LoadBalancerPort': 443,
                                      'Protocol': 'HTTPS',
                                      'SSLCertificateId': 'arn:aws:iam::000:server-certificate/cert'},
                         'PolicyNames': ['ELBSecurityPolicy-2015-05']}],
                    'LoadBalancerName': 'test-2',
                    'Policies': {'AppCookieStickinessPolicies': [],
                                 'LBCookieStickinessPolicies': [],
                                 'OtherPolicies': [
                                     'ELBSecurityPolicy-2015-05']},
                    'Scheme': 'internet-facing',
                    'SecurityGroups': ['sg-a97d82c1'],
                    'SourceSecurityGroup': {'GroupName': 'app-example-lb',
                                            'OwnerAlias': '576069677832'},
                    'Subnets': ['subnet-0000', 'subnet-0000'],
                    'VPCId': 'vpc-0000'}

    m_client.describe_load_balancers.side_effect = [
        {'ResponseMetadata': {'HTTPStatusCode': 200,
                              'RequestId': 'FakeId'},
         'LoadBalancerDescriptions': [description1],
         'NextMarker': 'something'},
        {'ResponseMetadata': {'HTTPStatusCode': 200,
                              'RequestId': 'FakeId'},
         'LoadBalancerDescriptions': [description2]},
        {'ResponseMetadata': {'HTTPStatusCode': 200,
                              'RequestId': 'FakeId'},
         'LoadBalancerDescriptions': [description1]},
    ]
    monkeypatch.setattr('boto3.client', m_client)

    elb = ELB.get_by_dns_name('example.eu-central-1.elb.amazonaws.com')
    assert elb.hosted_zone.id == "Z215JYRZR1TBD5"
    assert elb.region == 'eu-central-1'

    with pytest.raises(ELBNotFound):
        ELB.get_by_dns_name('example.eu-west-1.elb.amazonaws.com')
