import click
import responses
from mock import mock
from pytest import raises

from senza.components.elastigroup import ELASTIGROUP_RESOURCE_TYPE
from senza.spotinst.components.elastigroup_api import update_capacity, get_elastigroup, patch_elastigroup, deploy, \
    deploy_status, SPOTINST_API_URL, SpotInstAccountData, get_spotinst_account_data


def test_update_capacity():
    update = {
        'response': {
            'items': [{
                'id': 'sig-xfy',
                'name': 'my-app-1',
                'capacity': {
                    'minimum': 1,
                    'maximum': 3,
                    'target': 3,
                    'unit': 'instance'
                }
            }]
        }
    }

    elastigroup_id = 'sig-xfy'
    spotinst_account_data = SpotInstAccountData('act-zwk', 'fake-token')
    with responses.RequestsMock() as rsps:
        rsps.add(rsps.PUT,
                 '{}/aws/ec2/group/{}?accountId={}'.format(SPOTINST_API_URL, elastigroup_id,
                                                           spotinst_account_data.account_id),
                 status=200,
                 json=update)

        update_response = update_capacity(1, 3, 3, elastigroup_id, spotinst_account_data)[0]
        assert update_response['id'] == elastigroup_id
        assert update_response['name'] == 'my-app-1'
        assert update_response['capacity']['minimum'] == 1
        assert update_response['capacity']['maximum'] == 3
        assert update_response['capacity']['target'] == 3


def test_get_elastigroup():
    group = {
        'response': {
            'items': [{
                'id': 'sig-xfy',
                'name': 'my-app-1',
                'region': 'eu-central-1',
            }]
        }
    }

    elastigroup_id = 'sig-xfy'
    spotinst_account_data = SpotInstAccountData('act-zwk', 'fake-token')
    with responses.RequestsMock() as rsps:
        rsps.add(rsps.GET, '{}/aws/ec2/group/{}?accountId={}'.format(SPOTINST_API_URL, elastigroup_id,
                                                                     spotinst_account_data.account_id),
                 status=200,
                 json=group)

        group = get_elastigroup(elastigroup_id, spotinst_account_data)[0]
        assert group['id'] == elastigroup_id
        assert group['name'] == 'my-app-1'


def test_patch_elastigroup():
    patch = {
        'ImageId': 'image-foo',
        'InstanceType': 'm1.micro',
        'UserData': 'user-data-value'
    }

    update_response = {
        'response': {
            'items': [{
                'compute': {
                    'instanceTypes': {
                        'ondemand': 'm1.micro',
                        'spot': [
                            'm1.micro'
                        ]
                    },
                    'launchSpecification': {
                        'imageId': 'image-foo',
                        'userData': 'user-data-value'
                    }
                }
            }]
        }
    }
    with responses.RequestsMock() as rsps:
        spotinst_account_data = SpotInstAccountData('act-zwk', 'fake-token')
        elastigroup_id = 'sig-xfy'
        rsps.add(rsps.PUT, '{}/aws/ec2/group/{}?accountId={}'.format(SPOTINST_API_URL, elastigroup_id,
                                                                     spotinst_account_data.account_id),
                 status=200,
                 json=update_response)

        patch_response = patch_elastigroup(patch, elastigroup_id, spotinst_account_data)[0]
        assert patch_response['compute']['launchSpecification']['imageId'] == 'image-foo'
        assert patch_response['compute']['instanceTypes']['ondemand'] == 'm1.micro'
        assert patch_response['compute']['launchSpecification']['userData'] == 'user-data-value'


def test_deploy():
    response_json = {
        "response": {
            "items": [
                {
                    'id': 'deploy-id',
                    'status': 'STARTING',
                    'currentBatch': 1,
                    'numOfBatches': 1,
                    'progress': {
                        'unit': 'percentage',
                        'value': 0
                    }
                }
            ]
        }
    }
    with responses.RequestsMock() as rsps:
        spotinst_account_data = SpotInstAccountData('act-zwk', 'fake-token')
        elastigroup_id = 'sig-xfy'

        rsps.add(rsps.PUT, '{}/aws/ec2/group/{}/roll?accountId={}'.format(SPOTINST_API_URL, elastigroup_id,
                                                                          spotinst_account_data.account_id),
                 status=200,
                 json=response_json)

        deploy_response = deploy(batch_size=35, grace_period=50, elastigroup_id=elastigroup_id,
                                 spotinst_account_data=spotinst_account_data)[0]

        assert deploy_response['id'] == 'deploy-id'
        assert deploy_response['status'] == 'STARTING'
        assert deploy_response['numOfBatches'] == 1


def test_deploy_status():
    deploy_id = 'deploy-id-x'
    response_json = {
        "response": {
            "items": [
                {
                    'id': deploy_id,
                    'status': 'STARTING',
                    'currentBatch': 13,
                    'numOfBatches': 20,
                    'progress': {
                        'unit': 'percentage',
                        'value': 65
                    }
                }
            ]
        }
    }
    with responses.RequestsMock() as rsps:
        spotinst_account_data = SpotInstAccountData('act-zwk', 'fake-token')
        elastigroup_id = 'sig-xfy'

        rsps.add(rsps.GET, '{}/aws/ec2/group/{}/roll/{}?accountId={}'.format(SPOTINST_API_URL,
                                                                             elastigroup_id,
                                                                             deploy_id,
                                                                             spotinst_account_data.account_id),
                 status=200,
                 json=response_json)

        deploy_status_response = deploy_status(deploy_id, elastigroup_id, spotinst_account_data)[0]

        assert deploy_status_response['id'] == deploy_id
        assert deploy_status_response['numOfBatches'] == 20
        assert deploy_status_response['progress']['value'] == 65


def test_get_spotinst_account_data():
    template = {
        "TemplateBody": {
            "Mappings": {"Senza": {"Info": {"dont": "care"}}},
            "Resources": {
                "FakeResource1": {"Type": "Fake"},
                "TheOneWeCare": {
                    "Properties": {
                        "accessToken": "fake-token",
                        "accountId": "act-1234",
                        "group": {"dont": "care"}
                    },
                    "Type": ELASTIGROUP_RESOURCE_TYPE
                },
                "FakeResource2": {"Type": "Fake"},
            }
        }
    }

    with mock.patch('boto3.client') as MockHelper:
        MockHelper.return_value.get_template.return_value = template
        account_data = get_spotinst_account_data('fake-region', 'fake-stack-name')
        assert account_data.account_id == 'act-1234'
        assert account_data.access_token == 'fake-token'


def test_get_spotinst_account_data_failure():
    template = {
        "TemplateBody": {
            "Mappings": {"Senza": {"Info": {"dont": "care"}}},
            "Resources": {
                "FakeResource1": {"Type": "Fake"},
                "FakeResource2": {"Type": "Fake"},
            }
        }
    }

    with mock.patch('boto3.client') as MockHelper:
        MockHelper.return_value.get_template.return_value = template
        with raises(click.Abort, message="Expecting click.Abort error"):
            get_spotinst_account_data('fake-region', 'fake-stack-name')
