
import codecs
import datetime

import yaml

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
                if key == 'UserData' and isinstance(val, dict):
                    kwargs[key] = patch_user_data(kwargs[key], val)
                else:
                    kwargs[key] = val
            asg.create_launch_configuration(**kwargs)
            asg.update_auto_scaling_group(AutoScalingGroupName=group['AutoScalingGroupName'],
                                          LaunchConfigurationName=kwargs['LaunchConfigurationName'])
            changed = True
    return changed
