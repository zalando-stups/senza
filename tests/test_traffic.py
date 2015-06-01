from unittest.mock import MagicMock
from senza.aws import SenzaStackSummary
from senza.traffic import get_stack_versions, StackVersion


def test_get_stack_versions(monkeypatch):
    cf = MagicMock()
    elb = MagicMock()
    monkeypatch.setattr('senza.traffic.get_stacks', MagicMock(return_value=[]))
    monkeypatch.setattr('boto.cloudformation.connect_to_region', MagicMock(return_value=cf))
    monkeypatch.setattr('boto.ec2.elb.connect_to_region', MagicMock(return_value=elb))

    stack_version = list(get_stack_versions('my-stack', 'my-region'))

    assert stack_version == []

    stack = MagicMock(stack_name='my-stack-1')
    cf.describe_stacks.return_value = [MagicMock(tags={'StackVersion': '1'})]
    cf.describe_stack_resources.return_value = [
        MagicMock(resource_type='AWS::ElasticLoadBalancing::LoadBalancer'),
        MagicMock(resource_type='AWS::Route53::RecordSet', physical_resource_id='myapp.example.org')
    ]
    elb.get_all_load_balancers.return_value = [MagicMock(dns_name='elb-dns-name')]
    monkeypatch.setattr('senza.traffic.get_stacks', MagicMock(
        return_value=[SenzaStackSummary(stack), SenzaStackSummary(MagicMock(stack_status='ROLLBACK_COMPLETE'))]))
    stack_version = list(get_stack_versions('my-stack', 'my-region'))

    assert stack_version == [StackVersion('my-stack', '1', 'myapp.example.org', 'elb-dns-name')]
