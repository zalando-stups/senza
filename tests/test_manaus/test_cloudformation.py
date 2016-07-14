from unittest.mock import MagicMock
from datetime import datetime, timezone

from senza.manaus.cloudformation import CloudFormation, CloudFormationStack


MOCK_STACK1 = {'ResponseMetadata': {'HTTPStatusCode': 200,
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


def test_get_by_stack_name(monkeypatch):
    m_client = MagicMock()
    m_client.return_value = m_client

    m_client.describe_stacks.return_value = MOCK_STACK1
    monkeypatch.setattr('boto3.client', m_client)

    stack = CloudFormationStack.get_by_stack_name('myapp')
    assert stack.name == 'myapp-42'
    assert stack.tags['StackName'] == 'myapp'
    assert not stack.disable_rollback


def test_get_stacks(monkeypatch):
    status_filter = ["CREATE_IN_PROGRESS",
                     "CREATE_FAILED",
                     "CREATE_COMPLETE",
                     "ROLLBACK_IN_PROGRESS",
                     "ROLLBACK_FAILED",
                     "ROLLBACK_COMPLETE",
                     "DELETE_IN_PROGRESS",
                     "DELETE_FAILED",
                     "UPDATE_IN_PROGRESS",
                     "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
                     "UPDATE_COMPLETE",
                     "UPDATE_ROLLBACK_IN_PROGRESS",
                     "UPDATE_ROLLBACK_FAILED",
                     "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS",
                     "UPDATE_ROLLBACK_COMPLETE"]
    stack1 = {'StackId': 'arn:aws:cloudformation:eu-central-1:0000:stack/app-1/0000',
              'CreationTime': datetime(2016, 7, 13,
                                       9, 42, 45, 59000,
                                       tzinfo=timezone.utc),
              'StackName': 'app-1',
              'TemplateDescription': 'App ()',
              'StackStatus': 'CREATE_COMPLETE'}

    m_client = MagicMock()
    m_client.return_value = m_client
    m_client.list_stacks.return_value = {'StackSummaries': [stack1]}
    m_client.describe_stacks.return_value = MOCK_STACK1
    monkeypatch.setattr('boto3.client', m_client)
    cf = CloudFormation('eu-test-1')
    stacks = list(cf.get_stacks())
    assert len(stacks) == 1
    assert stacks[0].region == 'eu-test-1'
    m_client.list_stacks.assert_called_once_with(StackStatusFilter=status_filter)

    m_client.list_stacks.reset_mock()
    list(cf.get_stacks(all=True))
    m_client.list_stacks.assert_called_once_with(
        StackStatusFilter=[])
