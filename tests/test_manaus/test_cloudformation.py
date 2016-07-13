from unittest.mock import MagicMock
from datetime import datetime, timezone

from senza.manaus.cloudformation import CloudFormationStack


def test_get_by_stack_name(monkeypatch):
    m_client = MagicMock()
    m_client.return_value = m_client
    mock_stack = {'ResponseMetadata': {'HTTPStatusCode': 200,
                                       'RequestId': '000'},
                  'Stacks': [{'Capabilities': ['CAPABILITY_IAM'],
                              'CreationTime': datetime(2016, 7, 12,
                                                       17, 0, 0, 848000,
                                                       tzinfo=timezone.utc),
                              'Description': 'MyApp',
                              'DisableRollback': False,
                              'NotificationARNs': [],
                              'Parameters': [{'ParameterKey': 'ImageVersion',
                                              'ParameterValue': '42'}],
                              'StackId': 'arn:aws:cloudformation:eu-central-1:0000:stack/myapp-42/000',
                              'StackName': 'myapp-42',
                              'StackStatus': 'CREATE_COMPLETE',
                              'Tags': [{'Key': 'StackName', 'Value': 'myapp'},
                                       {'Key': 'Name',
                                        'Value': 'myapp-42'},
                                       {'Key': 'StackVersion',
                                        'Value': '42'}]}]}
    m_client.describe_stacks.return_value = mock_stack
    monkeypatch.setattr('boto3.client', m_client)

    stack = CloudFormationStack.get_by_stack_name('myapp')
    assert stack.name == 'myapp-42'
    assert stack.tags['StackName'] == 'myapp'
    assert not stack.disable_rollback
