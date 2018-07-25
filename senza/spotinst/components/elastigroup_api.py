'''
Wrapper methods for ElastiGroup's API
'''
import requests
import json


SPOTINST_API_URL = 'https://api.spotinst.io'


class SpotInstAccountData:
    '''
    Data required to access SpotInst API
    '''
    def __init__(self, account_id, access_token):
        self.account_id = account_id
        self.access_token = access_token


def update_elastigroup(body, elastigroup_id, spotinst_account_data):
    '''
    Performs the update ElastiGroup API call.

    Note: Although this should only return one element in the list,
     it still returns the entire list to prevent some silent decision making

    For more details see https://api.spotinst.com/elastigroup/amazon-web-services/update/
    '''
    headers = {
        "Authorization": "Bearer {}".format(spotinst_account_data.access_token),
        "Content-Type": "application/json"
    }

    response = requests.put(
        '{}/aws/ec2/group/{}?accountId={}'.format(SPOTINST_API_URL, elastigroup_id, spotinst_account_data.account_id),
        headers=headers, timeout=10, data=json.dumps(body))
    response.raise_for_status()
    data = response.json()
    groups = data.get("response", {}).get("items", [])

    return groups


def update_capacity(minimum, maximum, target, elastigroup_id, spotinst_account_data):
    '''
    Updates the capacity (number of instances) for an ElastiGroup by calling the SpotInst API.
    Returns the updated description of the ElastiGroup as a dict.
    Exceptions will be thrown for HTTP errors.
    '''

    new_capacity = {
        'target': target,
        'minimum': minimum,
        'maximum': maximum
    }

    body = {'group': {'capacity': new_capacity}}

    return update_elastigroup(body, elastigroup_id, spotinst_account_data)


def get_elastigroup(elastigroup_id, spotinst_account_data):
    '''
    Returns a list containing the description of an ElastiGroup as a dict.
    Exceptions will be thrown for HTTP errors.

    Note: Although this should only return one element in the list,
     it still returns the entire list to prevent some silent decision making

    For more details see https://api.spotinst.com/elastigroup/amazon-web-services/list-group/
    '''
    headers = {
        "Authorization": "Bearer {}".format(spotinst_account_data.access_token),
        "Content-Type": "application/json"
    }

    response = requests.get(
        'https://api.spotinst.io/aws/ec2/group/{}?accountId={}'.format(elastigroup_id, spotinst_account_data.account_id),
        headers=headers, timeout=5)
    response.raise_for_status()
    data = response.json()
    groups = data.get("response", {}).get("items", [])

    return groups


def patch_elastigroup(properties, elastigroup_id, spotinst_account_data):
    '''
    Patch specific properties of the ElastiGroup.
    '''
    compute = {}
    if 'InstanceType' in properties:
        compute['instanceTypes'] = {
            'ondemand': properties['InstanceType'],
        }

    if 'ImageId' in properties:
        compute.setdefault('launchSpecification', {})['imageId'] = properties['ImageId']

    if 'UserData' in properties:
        compute.setdefault('launchSpecification', {})['userData'] = properties['UserData']

    body = {'group': {'compute': compute}}
    return update_elastigroup(body, elastigroup_id, spotinst_account_data)
