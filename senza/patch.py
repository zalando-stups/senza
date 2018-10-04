
import codecs
import base64
import datetime

import yaml

from .spotinst.components import elastigroup_api
from .exceptions import InvalidUserDataType
from .manaus.boto_proxy import BotoClientProxy

LAUNCH_CONFIGURATION_PROPERTIES = set([
    'AssociatePublicIpAddress',
    'BlockDeviceMappings',
    'ClassicLinkVPCId',
    'ClassicLinkVPCSecurityGroups',
    'EbsOptimized',
    'IamInstanceProfile',
    'ImageId',
    'InstanceId',
    'InstanceMonitoring',
    'InstanceType',
    'KernelId',
    'KeyName',
    'LaunchConfigurationName',
    'PlacementTenancy',
    'RamdiskId',
    'SecurityGroups',
    'SpotPrice',
    'UserData',
])


def should_patch_user_data(new_val, old_val):
    '''
    Validate if User Data should be patched.
    '''
    current_user_data = yaml.safe_load(old_val)
    if isinstance(new_val, dict):
        return True
    elif isinstance(current_user_data, dict):
        raise InvalidUserDataType(type(current_user_data),
                                  type(new_val))
    return False


def patch_user_data(old: str, new: dict):
    first_line, sep, data = old.partition('\n')
    data = yaml.safe_load(data)
    if not isinstance(data, dict):
        raise ValueError('Instance user data has invalid YAML: must be key/value pairs')
    data.update(**new)
    return first_line + sep + yaml.safe_dump(data, default_flow_style=False)


def patch_auto_scaling_group(group: dict, region: str, properties: dict):
    asg = BotoClientProxy('autoscaling', region)
    result = asg.describe_launch_configurations(LaunchConfigurationNames=[group['LaunchConfigurationName']])
    lcs = result['LaunchConfigurations']
    changed = False
    for lc in lcs:
        lc_props = {k: lc[k] for k in properties}
        if properties != lc_props:
            # create new launch configuration with specified properties
            kwargs = {}
            for key in LAUNCH_CONFIGURATION_PROPERTIES:
                # NOTE: we only take non-empty values (otherwise the parameter validation will complain :-( )
                val = lc.get(key)
                if val is not None and val != '':
                    if key == 'UserData':
                        val = codecs.decode(val.encode('utf-8'), 'base64').decode('utf-8')
                    kwargs[key] = val
            now = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%S')
            kwargs['LaunchConfigurationName'] = '{}-{}'.format(kwargs['LaunchConfigurationName'][:64], now)
            for key, val in properties.items():

                if key == 'UserData':
                    if should_patch_user_data(val, kwargs['UserData']):
                        kwargs[key] = patch_user_data(kwargs[key], val)
                else:
                    kwargs[key] = val
            asg.create_launch_configuration(**kwargs)
            asg.update_auto_scaling_group(AutoScalingGroupName=group['AutoScalingGroupName'],
                                          LaunchConfigurationName=kwargs['LaunchConfigurationName'])
            changed = True
    return changed


def patch_elastigroup(group, properties, elastigroup_id, spotinst_account_data):
    '''
    Patch specific properties of an existing ElastiGroup
    '''
    changed = False
    properties_to_patch = {}

    group_user_data = group['compute']['launchSpecification']['userData']
    current_user_data = codecs.decode(group_user_data.encode('utf-8'), 'base64').decode('utf-8')

    current_properties = {
        'ImageId': group['compute']['launchSpecification']['imageId'],
        'InstanceType': group['compute']['instanceTypes']['ondemand'],
        'UserData': current_user_data
    }

    for key, val in properties.items():
        if key in current_properties:
            if key == 'UserData':
                if should_patch_user_data(val, current_properties[key]):
                    patched_user_data = patch_user_data(current_properties[key], val)
                    encoded_user_data = base64.b64encode(patched_user_data.encode('utf-8')).decode('utf-8')
                    properties_to_patch[key] = encoded_user_data
            else:
                if current_properties[key] != val:
                    properties_to_patch[key] = val

    if len(properties_to_patch) > 0:
        elastigroup_api.patch_elastigroup(properties_to_patch, elastigroup_id, spotinst_account_data)
        changed = True

    return changed
