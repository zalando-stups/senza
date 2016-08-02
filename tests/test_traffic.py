from unittest.mock import MagicMock
from senza.aws import SenzaStackSummary
from senza.traffic import get_stack_versions, StackVersion, get_weights, resolve_to_ip_addresses
from senza.manaus.route53 import RecordType


def test_get_stack_versions(monkeypatch):
    cf = MagicMock()
    elb = MagicMock()

    def my_boto3(service, *args):
        if service == 'cloudformation':
            return cf
        elif service == 'elb':
            return elb
        else:
            return MagicMock(side_effect=SyntaxError('unknown option'))

    monkeypatch.setattr('senza.traffic.get_stacks', MagicMock(return_value=[]))
    monkeypatch.setattr('boto3.client', my_boto3)
    monkeypatch.setattr('boto3.resource', my_boto3)

    stack_version = list(get_stack_versions('my-stack', 'my-region'))

    assert stack_version == []

    stack = MagicMock(stack_name='my-stack-1')
    resource = [
        MagicMock(resource_type='AWS::ElasticLoadBalancing::LoadBalancer'),
        MagicMock(resource_type='AWS::Route53::RecordSet',
                  physical_resource_id='myapp.example.org')
    ]
    cf.Stack.return_value = MagicMock(tags=[{'Value': '1', 'Key': 'StackVersion'}],
                                      notification_arns=['some-arn'],
                                      resource_summaries=MagicMock(all=MagicMock(return_value=resource)))
    elb.describe_load_balancers.return_value = {'LoadBalancerDescriptions': [{'DNSName': 'elb-dns-name'}]}
    monkeypatch.setattr('senza.traffic.get_stacks', MagicMock(
        return_value=[SenzaStackSummary(stack), SenzaStackSummary({'StackStatus': 'ROLLBACK_COMPLETE',
                                                                   'StackName': 'my-stack-1'})]))
    stack_version = list(get_stack_versions('my-stack', 'my-region'))
    assert stack_version == [StackVersion('my-stack', '1', ['myapp.example.org'], ['elb-dns-name'], ['some-arn'])]


def test_get_weights(monkeypatch):
    mock_route53 = MagicMock()
    mock_record1 = MagicMock(name='app1.example.com',
                             type=RecordType.A,
                             weight=100,
                             set_identifier='app-1')
    mock_route53.get_records.return_value = [mock_record1]
    monkeypatch.setattr('senza.traffic.Route53', mock_route53)
    all_identifiers = ['app-1', 'app-2', 'app-3']
    domains = ['app1.example.com']
    assert get_weights(domains, 'app-1', all_identifiers) == ({'app-1': 100,
                                                               'app-2': 0,
                                                               'app-3': 0},
                                                              0,
                                                              0)

    # Without weight
    mock_record2 = MagicMock(name='app1.example.com',
                             type=RecordType.A,
                             weight=None,
                             set_identifier='app-1')
    mock_route53.get_records.return_value = [mock_record2]

    all_identifiers = ['app-1', 'app-2', 'app-3']
    domains = ['app1.example.com']
    assert get_weights(domains, 'app-1', all_identifiers) == ({'app-1': 0,
                                                               'app-2': 0,
                                                               'app-3': 0},
                                                              0,
                                                              0)


def test_resolve_to_ip_addresses(monkeypatch):
    query = MagicMock()
    monkeypatch.setattr('dns.resolver.query', query)

    query.side_effect = Exception()
    assert resolve_to_ip_addresses('example.org') == set()

    query.side_effect = None
    query.return_value = [MagicMock(address='1.2.3.4')]
    assert resolve_to_ip_addresses('example.org') == {'1.2.3.4'}
