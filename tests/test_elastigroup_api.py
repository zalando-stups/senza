import responses
from senza.spotinst.components.elastigroup_api import update_capacity, get_elastigroup, patch_elastigroup, deploy, \
    SPOTINST_API_URL, SpotInstAccountData


def test_update_capacity(monkeypatch):
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


def test_get_elastigroup(monkeypatch):
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


def test_patch_elastigroup(monkeypatch):
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


def test_deploy(monkeypatch):
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
