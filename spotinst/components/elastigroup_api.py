'''
Wrapper methods for ElastiGroup's API
'''
import requests
import json


SPOTINST_API_URL = 'https://api.spotinst.io'


def update_capacity(minimum, maximum, target, elastigroup_id, spotinst_account_id, spotinst_token):
    '''
    Updates the capacity (number of instances) for an ElastiGroup by calling the SpotInst API.
    Returns the updated description of the ElastiGroup as a dict.
    Exceptions will be thrown for HTTP errors.

    For more details see https://api.spotinst.com/elastigroup/amazon-web-services/update/
    '''
    headers = {
        "Authorization": "Bearer {}".format(spotinst_token),
        "Content-Type": "application/json"
    }

    new_capacity = {
        'target': target,
        'minimum': minimum,
        'maximum': maximum
    }

    body = {'group': {'capacity': new_capacity}}
    response = requests.put(
        '{}/aws/ec2/group/{}?accountId={}'.format(SPOTINST_API_URL, elastigroup_id, spotinst_account_id),
        headers=headers, timeout=10, data=json.dumps(body))
    response.raise_for_status()
    data = response.json()
    groups = data.get("response", {}).get("items", [])

    return groups[0]


def get_elastigroup(elastigroup_id, spotinst_account_id, spotinst_token):
    '''
    Returns the description of an ElastiGroup as a dict.
    Exceptions will be thrown for HTTP errors.

    For more details see https://api.spotinst.com/elastigroup/amazon-web-services/list-group/
    '''
    headers = {
        "Authorization": "Bearer {}".format(spotinst_token),
        "Content-Type": "application/json"
    }

    response = requests.get(
        'https://api.spotinst.io/aws/ec2/group/{}?accountId={}'.format(elastigroup_id, spotinst_account_id),
        headers=headers, timeout=5)
    response.raise_for_status()
    data = response.json()
    groups = data.get("response", {}).get("items", [])

    return groups[0]
