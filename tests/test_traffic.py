from unittest.mock import MagicMock
from senza.aws import SenzaStackSummary
from senza.traffic import get_stack_versions, StackVersion


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
        MagicMock(resource_type='AWS::Route53::RecordSet', physical_resource_id='myapp.example.org')
    ]
    cf.Stack.return_value = MagicMock(tags=[{'Value': '1', 'Key': 'StackVersion'}], notification_arns=['some-arn'],
                                      resource_summaries=MagicMock(all=MagicMock(return_value=resource)))
    elb.describe_load_balancers.return_value = {'LoadBalancerDescriptions': [{'DNSName': 'elb-dns-name'}]}
    monkeypatch.setattr('senza.traffic.get_stacks', MagicMock(
        return_value=[SenzaStackSummary(stack), SenzaStackSummary({'StackStatus': 'ROLLBACK_COMPLETE',
                                                                   'StackName': 'my-stack-1'})]))
    stack_version = list(get_stack_versions('my-stack', 'my-region'))
    assert stack_version == [StackVersion('my-stack', '1', ['myapp.example.org'], ['elb-dns-name'], ['some-arn'])]
