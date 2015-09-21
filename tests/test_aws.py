from unittest.mock import MagicMock
from senza.aws import resolve_topic_arn
from senza.aws import get_security_group, resolve_security_groups, get_account_id, get_account_alias


def test_resolve_security_groups(monkeypatch):
    ec2 = MagicMock()
    ec2.security_groups.filter.return_value = [MagicMock(name='app-test', id='sg-test')]
    monkeypatch.setattr('boto3.resource', MagicMock(return_value=ec2))

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
    topic = MagicMock(arn='arn:123:mytopic')
    sns.topics.all.return_value = [topic]
    monkeypatch.setattr('boto3.resource', MagicMock(return_value=sns))

    assert 'arn:123:mytopic' == resolve_topic_arn('myregion', 'mytopic')


def test_get_account_id(monkeypatch):
    boto3 = MagicMock()
    boto3.get_user.return_value = {'User': {'Arn': 'arn:aws:iam::0123456789:user/admin'}}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))

    assert '0123456789' == get_account_id()

    boto3 = MagicMock()
    boto3.get_user.side_effect = Exception()
    boto3.list_roles.return_value = {'Roles': [{'Arn': 'arn:aws:iam::0123456789:role/role-test'}]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))

    assert '0123456789' == get_account_id()

    boto3 = MagicMock()
    boto3.get_user.side_effect = Exception()
    boto3.list_roles.return_value = {'Roles': []}
    boto3.list_users.return_value = {'Users': [{'Arn': 'arn:aws:iam::0123456789:user/user-test'}]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))

    assert '0123456789' == get_account_id()

    boto3 = MagicMock()
    boto3.get_user.side_effect = Exception()
    boto3.list_roles.return_value = {'Roles': []}
    boto3.list_users.return_value = {'Users': []}
    boto3.list_saml_providers.return_value = {'SAMLProviderList': [{'Arn': 'arn:aws:iam::0123456789:saml-provider/saml-test'}]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))

    assert '0123456789' == get_account_id()

    boto3 = MagicMock()
    boto3.get_user.side_effect = Exception()
    boto3.list_roles.return_value = {'Roles': []}
    boto3.list_users.return_value = {'Users': []}
    boto3.list_saml_providers.return_value = {'SAMLProviderList': []}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))

    assert get_account_id() is None


def test_get_account_alias(monkeypatch):
    boto3 = MagicMock()
    boto3.list_account_aliases.return_value = {'AccountAliases': ['org-dummy']}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))

    assert 'org-dummy' == get_account_alias()
