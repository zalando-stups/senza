'''
Wrapper methods for ElastiGroup's API
'''
import click
import requests
import json
import boto3

from senza.components.elastigroup import ELASTIGROUP_RESOURCE_TYPE

SPOTINST_API_URL = 'https://api.spotinst.io'

DEPLOY_STRATEGY_RESTART = 'RESTART_SERVER'
DEPLOY_STRATEGY_REPLACE = 'REPLACE_SERVER'
DEFAULT_CONNECT_TIMEOUT = 9
DEFAULT_READ_TIMEOUT = 30


class SpotInstAccountData:
    '''
    Data required to access SpotInst API
    '''

    def __init__(self, account_id, access_token):
        self.account_id = account_id
        self.access_token = access_token


def get_spotinst_account_data(region, stack_name):
    """
    Extracts the Spotinst API access token and cloud account ID required to use the SpotInst API
    It returns those parameters from the first resource of Type ``Custom::elastigroup``
    found in the stack with the name and region provided as arguments
    """
    cf = boto3.client('cloudformation', region)
    template = cf.get_template(StackName=stack_name)['TemplateBody']

    resources = template.get('Resources', [])
    for name, resource in resources.items():
        if resource.get("Type", None) == ELASTIGROUP_RESOURCE_TYPE:
            spotinst_token = resource['Properties']['accessToken']
            spotinst_account_id = resource['Properties']['accountId']
            return SpotInstAccountData(spotinst_account_id, spotinst_token)

    raise click.Abort()


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
        headers=headers, timeout=(DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT), data=json.dumps(body))
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
        '{}/aws/ec2/group/{}?accountId={}'.format(SPOTINST_API_URL, elastigroup_id, spotinst_account_data.account_id),
        headers=headers, timeout=(DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT))
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


def deploy(batch_size=20, grace_period=300, strategy=DEPLOY_STRATEGY_REPLACE,
           elastigroup_id=None, spotinst_account_data=None):
    '''
    Triggers Blue/Green Deployment that replaces the existing instances in the Elastigroup

    For more details see https://api.spotinst.com/elastigroup/amazon-web-services/deploy/
    '''
    headers = {
        "Authorization": "Bearer {}".format(spotinst_account_data.access_token),
        "Content-Type": "application/json"
    }

    body = {
        'batchSizePercentage': batch_size,
        'gracePeriod': grace_period,
        'strategy': {
            'action': strategy
        }
    }

    response = requests.put(
        '{}/aws/ec2/group/{}/roll?accountId={}'.format(SPOTINST_API_URL, elastigroup_id,
                                                       spotinst_account_data.account_id),
        headers=headers, timeout=(DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT), data=json.dumps(body))
    response.raise_for_status()
    data = response.json()
    deploys = data.get("response", {}).get("items", [])

    return deploys


def deploy_status(deploy_id, elastigroup_id, spotinst_account_data):
    '''
    Obtains the current status of a deployment.

    For more details see https://api.spotinst.com/elastigroup/amazon-web-services/deploy-status/
    '''
    headers = {
        "Authorization": "Bearer {}".format(spotinst_account_data.access_token),
        "Content-Type": "application/json"
    }

    response = requests.get(
        '{}/aws/ec2/group/{}/roll/{}?accountId={}'.format(SPOTINST_API_URL, elastigroup_id, deploy_id,
                                                          spotinst_account_data.account_id),
        headers=headers, timeout=(DEFAULT_CONNECT_TIMEOUT, DEFAULT_READ_TIMEOUT))
    response.raise_for_status()
    data = response.json()
    deploys = data.get("response", {}).get("items", [])

    return deploys
