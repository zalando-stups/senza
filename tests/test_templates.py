import click
import botocore
from unittest.mock import MagicMock
from senza.templates._helper import (create_mint_read_policy_document, get_mint_bucket_name,
                                     check_value, prompt, choice, attach_cross_stack_policy)
from senza.templates.postgresapp import (ebs_optimized_supported,
                                         generate_random_password,
                                         set_default_variables,
                                         generate_definition,
                                         get_latest_image)
from senza.utils import CROSS_STACK_POLICY_NAME


def test_template_helper_get_mint_bucket_name(monkeypatch):
    monkeypatch.setattr('senza.templates._helper.get_account_id', MagicMock(return_value=123))
    monkeypatch.setattr('senza.templates._helper.get_account_alias', MagicMock(return_value='myorg-foobar'))
    s3 = MagicMock()
    s3.return_value.Bucket.return_value.name = 'myorg-stups-mint-123-myregion'
    monkeypatch.setattr('boto3.resource', s3)

    assert 'myorg-stups-mint-123-myregion' == get_mint_bucket_name('myregion'), 'Find Mint Bucket'

    s3 = MagicMock()
    s3.return_value.Bucket.return_value.load.side_effect = Exception()
    monkeypatch.setattr('boto3.resource', s3)
    assert 'myorg-stups-mint-123-otherregion' == get_mint_bucket_name('otherregion'), \
           'Return Name of Bucket, if no other Bucket found'

    exist_bucket = MagicMock()
    exist_bucket.name = 'myorg-stups-mint-123-myregion'
    s3 = MagicMock()
    s3.return_value.Bucket.return_value.load.side_effect = Exception()
    s3.return_value.buckets.all.return_value = [exist_bucket]
    monkeypatch.setattr('boto3.resource', s3)
    assert 'myorg-stups-mint-123-myregion' == get_mint_bucket_name('otherregion'), 'Find Mint bucket in other Region'


def test_template_helper_get_iam_role_policy(monkeypatch):
    expected_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowMintRead",
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject"
                ],
                "Resource": [
                    "arn:aws:s3:::bucket-name/myapp/*"
                ]
            },
        ]
    }

    assert expected_policy == create_mint_read_policy_document('myapp', 'bucket-name', 'myregion')


def test_template_helper_check_value():
    f = check_value(5, '^[A-Z]+$')
    assert 'ABC' == f('ABC')
    try:
        f('abc')
    except click.UsageError:
        pass
    except:
        assert False, 'check_value raise with a unkown exception'
    else:
        assert False, 'check_value doesnot return with a raise'

    try:
        f('ABCABC')
    except click.UsageError:
        pass
    except:
        assert False, 'check_value raise with a unkown exception'
    else:
        assert False, 'check_value doesnot return with a raise'


def test_attach_cross_stack_policy(monkeypatch):
    role_name = "myrole"

    iam = MagicMock()
    iam.return_value = iam

    cross_stack_policy_mock = MagicMock()
    cross_stack_policy_mock.return_value = {'PolicyName': CROSS_STACK_POLICY_NAME, 'Arn': 'arn:aws:iam::aws:policy/' +
                                                                                          CROSS_STACK_POLICY_NAME}

    monkeypatch.setattr('boto3.client', iam)
    monkeypatch.setattr('senza.manaus.iam.find_or_create_policy', cross_stack_policy_mock)

    # Test case 1 :: role already exists, policy is not yet attached
    get_role_policy_error_response = {'Error': {'Code': 'Error getting the role policy'}}
    iam.get_role_policy.side_effect = botocore.exceptions.ClientError(get_role_policy_error_response, 'get_role_policy')

    iam.attach_role_policy.return_value = {'ResponseMetadata': {'key': 'value'}}

    role_exists = True
    role_created = False
    attach_cross_stack_policy(role_exists, role_created, role_name, iam)

    assert iam.get_role_policy.call_count == 1
    assert iam.attach_role_policy.call_count == 1

    # Test case 2 :: role already exists, policy is already attached
    iam.reset_mock()

    iam.get_role_policy.side_effect = {'RoleName': 'myrolepolicy'}

    role_exists = True
    role_created = False
    attach_cross_stack_policy(role_exists, role_created, role_name, iam)

    assert iam.get_role_policy.call_count == 1
    assert iam.attach_role_policy.call_count == 0

    # Test case 3 :: role was just created, policy is not yet attached
    iam.reset_mock()

    get_role_policy_error_response = {'Error': {'Code': 'Error getting the role policy'}}
    iam.get_role_policy.side_effect = botocore.exceptions.ClientError(get_role_policy_error_response, 'get_role_policy')

    iam.attach_role_policy.return_value = {'ResponseMetadata': {'key': 'value'}}

    role_exists = False
    role_created = True
    attach_cross_stack_policy(role_exists, role_created, role_name, iam)

    assert iam.get_role_policy.call_count == 0
    assert iam.attach_role_policy.call_count == 1


def test_choice_callable_default(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr('clickclick.choice', mock)
    variables = {}
    choice(variables, 'test', default=lambda: 'default')
    mock.assert_called_once_with(default='default')


def test_prompt_callable_default(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr('click.prompt', mock)
    variables = {}
    prompt(variables, 'test', default=lambda: 'default')
    mock.assert_called_once_with(default='default')


def test_choice_type():
    variables = {'test': '42'}
    choice(variables, 'test', type=int)
    assert variables['test'] == 42


def test_prompt_type():
    variables = {'test': '42'}
    prompt(variables, 'test', type=int)
    assert variables['test'] == 42


def test_ebs_optimized_supported():
    assert ebs_optimized_supported('c3.xlarge')
    assert not ebs_optimized_supported('t2.micro')


def test_generate_random_password():
    assert len(generate_random_password(62)) == 62


def test_generate_definition():
    variables = set_default_variables(dict())
    assert len(generate_definition(variables)) > 300


def test_get_latest_image(monkeypatch):

    mock_response = MagicMock()
    mock_response.json.return_value = [{'created': '2016-06-09T07:12:34.413Z',
                                        'created_by': 'someone',
                                        'name': '0.90-p7'},
                                       {'created': '2016-06-28T10:19:47.788Z',
                                        'created_by': 'someone',
                                        'name': '0.90-p8'},
                                       {'created': '2016-07-01T06:58:32.956Z',
                                        'created_by': 'someone',
                                        'name': '0.90-test'},
                                       {'created': '2016-07-12T06:58:32.956Z',
                                        'created_by': 'someone',
                                        'name': '0.91-SNAPSHOT'}]

    mock_get = MagicMock()
    mock_get.return_value = mock_response
    monkeypatch.setattr('requests.get', mock_get)

    assert get_latest_image() == 'registry.opensource.zalan.do/acid/spilo-9.5:0.90-test'

    mock_response.ok = False
    assert get_latest_image() == ''
