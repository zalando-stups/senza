import json
from datetime import datetime, timezone
from unittest.mock import MagicMock

import botocore.exceptions
import pytest
from senza.manaus.cloudformation import CloudFormation, CloudFormationStack
from senza.manaus.exceptions import StackNotFound, StackNotUpdated

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
    stack1 = {
        'StackId': 'arn:aws:cloudformation:eu-central-1:0000:stack/app-1/0000',
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
    m_client.list_stacks.assert_called_once_with(
        StackStatusFilter=status_filter)

    m_client.list_stacks.reset_mock()
    list(cf.get_stacks(all=True))
    m_client.list_stacks.assert_called_once_with(
        StackStatusFilter=[])


def test_cf_resources(monkeypatch):
    summary = [{'LastUpdatedTimestamp': datetime(2016, 7, 20, 7, 3, 7,
                                                 108000,
                                                 tzinfo=timezone.utc),
                'LogicalResourceId': 'AppLoadBalancer',
                'PhysicalResourceId': 'myapp1-1',
                'ResourceStatus': 'CREATE_COMPLETE',
                'ResourceType': 'AWS::ElasticLoadBalancing::LoadBalancer'},
               {'LastUpdatedTimestamp': datetime(2016, 7, 20, 7, 3,
                                                 45, 70000,
                                                 tzinfo=timezone.utc),
                'LogicalResourceId': 'AppLoadBalancerMainDomain',
                'PhysicalResourceId': 'myapp1.example.com',
                'ResourceStatus': 'CREATE_COMPLETE',
                'ResourceType': 'AWS::Route53::RecordSet'},
               {'LastUpdatedTimestamp': datetime(2016, 7, 20, 7, 3,
                                                 45, 70000,
                                                 tzinfo=timezone.utc),
                'LogicalResourceId': 'ThisWillBeIgnored',
                'ResourceStatus': 'CREATE_COMPLETE',
                'ResourceType': 'AWS::Route53::RecordSet'},
               {'LastUpdatedTimestamp': datetime(2016, 7, 20, 7, 3,
                                                 43, 871000,
                                                 tzinfo=timezone.utc),
                'LogicalResourceId': 'AppLoadBalancerVersionDomain',
                'PhysicalResourceId': 'myapp1-1.example.com',
                'ResourceStatus': 'CREATE_COMPLETE',
                'ResourceType': 'AWS::Route53::RecordSet'},
               {'LastUpdatedTimestamp': datetime(2016, 7, 20, 7, 7,
                                                 38, 495000,
                                                 tzinfo=timezone.utc),
                'LogicalResourceId': 'AppServer',
                'PhysicalResourceId': 'myapp1-1-AppServer-00000',
                'ResourceStatus': 'CREATE_COMPLETE',
                'ResourceType': 'AWS::AutoScaling::AutoScalingGroup'},
               {'LastUpdatedTimestamp': datetime(2016, 7, 20, 7, 5,
                                                 10, 48000,
                                                 tzinfo=timezone.utc),
                'LogicalResourceId': 'AppServerConfig',
                'PhysicalResourceId': 'myapp1-1-AppServerConfig-00000',
                'ResourceStatus': 'CREATE_COMPLETE',
                'ResourceType': 'AWS::AutoScaling::LaunchConfiguration'},
               {'LastUpdatedTimestamp': datetime(2016, 7, 20, 7, 5, 6,
                                                 745000,
                                                 tzinfo=timezone.utc),
                'LogicalResourceId': 'AppServerInstanceProfile',
                'PhysicalResourceId': 'myapp1-1-AppServerInstanceProfile-000',
                'ResourceStatus': 'CREATE_COMPLETE',
                'ResourceType': 'AWS::IAM::InstanceProfile'}]

    response = {'ResponseMetadata': {'HTTPStatusCode': 200,
                                     'RequestId': '0000'},
                'StackResourceSummaries': summary}

    mock_client = MagicMock()
    mock_client.return_value = mock_client
    mock_client.list_stack_resources.return_value = response
    mock_client.describe_stacks.return_value = MOCK_STACK1
    monkeypatch.setattr('boto3.client', mock_client)

    mock_route53 = MagicMock()
    mock_route53.side_effect = [[MagicMock(set_identifier=None)],
                                [MagicMock(set_identifier='myapp-42')]]
    monkeypatch.setattr('senza.manaus.cloudformation.Route53.get_records',
                        mock_route53)

    stack = CloudFormationStack.get_by_stack_name('myapp')

    resources = list(stack.resources)
    mock_route53.assert_any_call(name='myapp1.example.com')
    mock_route53.assert_any_call(name='myapp1-1.example.com')
    assert len(resources) == 2


def test_get_by_stack_name_not_found(monkeypatch):
    m_client = MagicMock()
    m_client.return_value = m_client

    m_client.describe_stacks.side_effect = botocore.exceptions.ClientError(
        {'Error': {'Code': 'ValidationError',
                   'Message': 'Stack with id myapp does not exist'}},
        'foobar')
    monkeypatch.setattr('boto3.client', m_client)

    with pytest.raises(StackNotFound):
        CloudFormationStack.get_by_stack_name('myapp')

    m_client.describe_stacks.side_effect = botocore.exceptions.ClientError(
        {'Error': {'Code': 'ValidationError',
                   'Message': 'Random'}},
        'foobar')
    with pytest.raises(botocore.exceptions.ClientError):
        CloudFormationStack.get_by_stack_name('myapp')


def test_template(monkeypatch):
    m_client = MagicMock()
    m_client.return_value = m_client

    m_client.describe_stacks.return_value = MOCK_STACK1
    m_client.get_template.return_value = {'TemplateBody':
                                          {'answer_to_life_the_universe_and_everything': 42}}
    monkeypatch.setattr('boto3.client', m_client)

    stack = CloudFormationStack.get_by_stack_name('myapp')
    assert stack.template == {'answer_to_life_the_universe_and_everything': 42}

    m_client.get_template.assert_called_once_with(StackName='myapp-42')

    # The 2nd time it should use a cached value
    m_client.get_template.reset_mock()
    assert stack.template == {'answer_to_life_the_universe_and_everything': 42}
    assert m_client.get_template_assert_not_called()

    # After reset it should fetch the template again
    m_client.get_template.reset_mock()
    stack.reset()
    assert stack.template == {'answer_to_life_the_universe_and_everything': 42}
    m_client.get_template.assert_called_once_with(StackName='myapp-42')


def test_stack_update(monkeypatch):
    m_client = MagicMock()
    m_client.return_value = m_client

    m_client.describe_stacks.return_value = MOCK_STACK1
    m_client.get_template.return_value = {'TemplateBody':
                                          {'answer_to_life_the_universe_and_everything': 42}}
    monkeypatch.setattr('boto3.client', m_client)

    stack = CloudFormationStack.get_by_stack_name('myapp')

    stack.template["What not to do"] = "Panic"
    stack.parameters['SomethingElse'] = "CompletelyDifferent"

    stack.update()

    parameters = [{'ParameterValue': '42', 'ParameterKey': 'ImageVersion'},
                  {'ParameterKey': 'SomethingElse',
                   'ParameterValue': 'CompletelyDifferent'}]
    template = {"answer_to_life_the_universe_and_everything": 42,
                "What not to do": "Panic"}
    m_client.update_stack.assert_called_once_with(Capabilities=['CAPABILITY_IAM'],
                                                  Parameters=parameters,
                                                  StackName='myapp-42',
                                                  TemplateBody=json.dumps(template))

    m_client.update_stack.side_effect = botocore.exceptions.ClientError(
        {'Error': {'Code': 'ValidationError',
                   'Message': 'No updates are to be performed.'}},
        'foobar')

    with pytest.raises(StackNotUpdated):
        stack.update()

    m_client.update_stack.side_effect = botocore.exceptions.ClientError(
        {'Error': {'Code': 'ValidationError',
                   'Message': 'Random'}},
        'foobar')

    with pytest.raises(botocore.exceptions.ClientError):
        stack.update()
