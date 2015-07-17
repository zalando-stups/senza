from unittest.mock import MagicMock
from senza.aws import resolve_topic_arn
import boto.ec2
from senza.aws import get_security_group, resolve_security_groups, get_account_id, get_account_alias

def test_resolve_security_groups(monkeypatch):
    ec2 = MagicMock()
    sg = boto.ec2.securitygroup.SecurityGroup(name='app-test', id='sg-test')
    ec2.get_all_security_groups.return_value = [sg]
    monkeypatch.setattr('boto.ec2.connect_to_region', MagicMock(return_value=ec2))

    security_groups = []
    security_groups.append({'Fn::GetAtt': ['RefSecGroup', 'GroupId']})
    security_groups.append('sg-007')
    security_groups.append('app-test')

    result = []
    result.append({'Fn::GetAtt': ['RefSecGroup', 'GroupId']})
    result.append('sg-007')
    result.append('sg-test')

    assert result == resolve_security_groups(security_groups, 'myregion')

def test_create(monkeypatch):
    sns = MagicMock()
    topic = {'TopicArn': 'arn:123:mytopic'}
    sns.get_all_topics.return_value = {'ListTopicsResponse': {'ListTopicsResult': {'Topics': [topic]}}}
    monkeypatch.setattr('boto.sns.connect_to_region', MagicMock(return_value=sns))

    assert 'arn:123:mytopic' == resolve_topic_arn('myregion', 'mytopic')


def test_get_account_id(monkeypatch):
    boto3 = MagicMock()
    boto3.get_user.return_value = {'User': {'Arn': 'arn:aws:iam::0123456789:user/admin'}}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))

    assert '0123456789' == get_account_id()


def test_get_account_alias(monkeypatch):
    boto3 = MagicMock()
    boto3.list_account_aliases.return_value = {'AccountAliases': ['org-dummy']}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))

    assert 'org-dummy' == get_account_alias()
