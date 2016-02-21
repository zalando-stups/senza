from unittest.mock import MagicMock, Mock
from senza.aws import resolve_topic_arn
from senza.aws import get_security_group, resolve_security_groups, get_account_id, get_account_alias, list_kms_keys, encrypt, get_vpc_attribute, resolve_referenced_resource


def test_get_security_group(monkeypatch):
    ec2 = MagicMock()
    monkeypatch.setattr('boto3.resource', MagicMock(return_value=ec2))

    results = None
    assert results == get_security_group('myregion', 'group_inexistant')
    

def test_resolve_security_groups(monkeypatch):
    ec2 = MagicMock()
    ec2.security_groups.filter = MagicMock(side_effect=[
        [MagicMock(name='app-test', id='sg-test')],
        [MagicMock(name='physical-resource-id', id='sg-resource')]])

    def my_resource(rtype, *args):
        if rtype == 'ec2':
            return ec2
        else:
            return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'cloudformation':
            cf = MagicMock()
            resource = {'StackResourceDetail': {'ResourceStatus': 'CREATE_COMPLETE', 
                'ResourceType': 'AWS::EC2::SecurityGroup',
                'PhysicalResourceId': 'physical-resource-id'}}
            cf.describe_stack_resource.return_value = resource
            return cf
        else:
            return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('boto3.client', my_client)

    security_groups = []
    security_groups.append({'Fn::GetAtt': ['RefSecGroup', 'GroupId']})
    security_groups.append('sg-007')
    security_groups.append('app-test')
    security_groups.append({'Stack': 'stack', 'LogicalId': 'id'})

    result = []
    result.append({'Fn::GetAtt': ['RefSecGroup', 'GroupId']})
    result.append('sg-007')
    result.append('sg-test')
    result.append('sg-resource')

    assert result == resolve_security_groups(security_groups, 'myregion')


def test_create(monkeypatch):
    sns = MagicMock()
    topic = MagicMock(arn='arn:123:mytopic')
    sns.topics.all.return_value = [topic]
    monkeypatch.setattr('boto3.resource', MagicMock(return_value=sns))

    assert 'arn:123:mytopic' == resolve_topic_arn('myregion', 'mytopic')


def test_encrypt(monkeypatch):
    boto3 = MagicMock()
    boto3.encrypt.return_value = {'CiphertextBlob':b'Hello World'}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))

    assert b'Hello World' == encrypt(region=None, KeyId='key_a', Plaintext='Hello World', b64encode=False)
    assert 'SGVsbG8gV29ybGQ=' == encrypt(region=None, KeyId='key_a', Plaintext='Hello World', b64encode=True)


def test_list_kms_keys(monkeypatch):
    boto3 = MagicMock()
    boto3.list_keys.return_value = {'Keys': [{'KeyId':'key_a'},{'KeyId':'key_b'}]}
    boto3.list_aliases.return_value = {'Aliases': [{'AliasName':'a', 'TargetKeyId':'key_a'}]}
    boto3.describe_key.return_value = {'KeyMetadata':{'Description':'This is key a'}}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))

    assert len(list_kms_keys(region=None, details=True)) == 2


def test_get_vpc_attribute(monkeypatch):
    from collections import namedtuple

    ec2 = MagicMock()
    ec2.Vpc.return_value = namedtuple('a','VpcId')('dummy')

    boto3 = MagicMock()
    monkeypatch.setattr('boto3.resource', MagicMock(return_value=ec2))

    assert get_vpc_attribute('r', 'a', 'VpcId') == 'dummy'
    assert get_vpc_attribute('r', 'a', 'nonexistent') is None


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

def test_resolve_referenced_resource(monkeypatch):
    boto3 = MagicMock()
    resource = {'StackResourceDetail': {'ResourceStatus':'CREATE_COMPLETE', 
        'ResourceType': 'AWS::EC2::Something',
        'PhysicalResourceId':'some-resource'}}
    boto3.describe_stack_resource.return_value = resource
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    
    ref = {'Fn::GetAtt': ['RefSecGroup', 'GroupId']}
    assert ref == resolve_referenced_resource(ref, 'region')

    ref = {'Stack': 'stack', 'LogicalId': 'id'}
    assert 'some-resource' == resolve_referenced_resource(ref, 'region')

    resource['StackResourceDetail']['ResourceStatus'] = 'CREATE_IN_PROGRESS'
    try:
        resolve_referenced_resource(ref, 'region')
    except ValueError:
        pass
    else:
        assert False, "resolving referenced resource failed"