import codecs

from unittest.mock import MagicMock
import pytest
import base64

from senza.exceptions import InvalidUserDataType
from senza.patch import patch_auto_scaling_group, patch_elastigroup
from senza.spotinst.components.elastigroup_api import SpotInstAccountData


def test_patch_auto_scaling_group(monkeypatch):

    lc = {'ImageId': 'originalimage', 'LaunchConfigurationName': 'originallc',
          'UserData': codecs.encode(b'myuserdata', 'base64').decode('utf-8')}
    result = {'LaunchConfigurations': [lc]}

    asg = MagicMock()
    asg.describe_launch_configurations.return_value = result

    new_lc = {}

    def create_lc(**kwargs):
        new_lc.update(kwargs)

    asg.create_launch_configuration = create_lc
    monkeypatch.setattr('boto3.client', lambda x, region: asg)
    group = {'AutoScalingGroupName': 'myasg', 'LaunchConfigurationName': 'originallc'}
    properties = {'ImageId': 'mynewimage'}
    patch_auto_scaling_group(group, 'myregion', properties)

    assert new_lc['UserData'] == 'myuserdata'


def test_patch_elastigroup(monkeypatch):
    spotinst_account_data = SpotInstAccountData('act-zwk', 'fake-token')
    elastigroup_id = 'sig-xfy'

    new_lc = {}

    def create_lc(properties_to_patch, *args):
        new_lc.update(properties_to_patch)

    monkeypatch.setattr('senza.spotinst.components.elastigroup_api.patch_elastigroup', create_lc)

    properties = {'ImageId': 'mynewimage', 'InstanceType': 'mynewinstancetyoe', 'UserData': {'source': 'newsource >'}}
    group = {'compute': {
            'launchSpecification': {
                'userData': base64.b64encode('#firstline\nsource: oldsource\n'.encode('utf-8')).decode('utf-8'),
                'imageId': 'myoldimage'
            },
            'instanceTypes': {
                'ondemand': 'myoldinstancetyoe'
            }
        }
    }
    changed = patch_elastigroup(group, properties, elastigroup_id, spotinst_account_data)

    assert changed
    assert new_lc['ImageId'] == 'mynewimage'
    assert new_lc['UserData'] == base64.b64encode('#firstline\nsource: newsource >\n'.encode('utf-8')).decode('utf-8')
    assert new_lc['InstanceType'] == 'mynewinstancetyoe'


def test_patch_auto_scaling_group_taupage_config(monkeypatch):

    lc = {'ImageId': 'originalimage', 'LaunchConfigurationName': 'originallc',
          'UserData': codecs.encode(b'#firstline\nsource: oldsource', 'base64').decode('utf-8')}
    result = {'LaunchConfigurations': [lc]}

    asg = MagicMock()
    asg.describe_launch_configurations.return_value = result

    new_lc = {}

    def create_lc(**kwargs):
        new_lc.update(kwargs)

    asg.create_launch_configuration = create_lc
    monkeypatch.setattr('boto3.client', lambda x, region: asg)
    group = {'AutoScalingGroupName': 'myasg', 'LaunchConfigurationName': 'originallc'}
    properties = {'UserData': {'source': 'newsource'}}
    patch_auto_scaling_group(group, 'myregion', properties)

    assert new_lc['UserData'] == '#firstline\nsource: newsource\n'


def test_patch_user_data_wrong_type(monkeypatch):

    lc = {'ImageId': 'originalimage', 'LaunchConfigurationName': 'originallc',
          'UserData': codecs.encode(b'#firstline\nsource: oldsource', 'base64').decode('utf-8')}
    result = {'LaunchConfigurations': [lc]}

    asg = MagicMock()
    asg.describe_launch_configurations.return_value = result

    new_lc = {}

    def create_lc(**kwargs):
        new_lc.update(kwargs)

    asg.create_launch_configuration = create_lc
    monkeypatch.setattr('boto3.client', lambda x, region: asg)
    group = {'AutoScalingGroupName': 'myasg', 'LaunchConfigurationName': 'originallc'}
    properties = {'UserData': "it's a string"}
    with pytest.raises(InvalidUserDataType) as exc_info:
        patch_auto_scaling_group(group, 'myregion', properties)

    assert str(exc_info.value) == ('Current user data is a map but provided '
                                   'user data is a string.')


def test_patch_user_data_wrong_type_elastigroup(monkeypatch):
    spotinst_account_data = SpotInstAccountData('act-zwk', 'fake-token')
    elastigroup_id = 'sig-xfy'

    properties = {'UserData': "it's a string"}
    group = {'compute': {
        'launchSpecification': {
            'userData': codecs.encode(b'#firstline\nsource: oldsource', 'base64').decode('utf-8'),
            'imageId': 'myoldimage'
        },
        'instanceTypes': {
            'ondemand': 'myoldinstancetyoe'
        }
    }
    }
    with pytest.raises(InvalidUserDataType) as exc_info:
        patch_elastigroup(group, properties, elastigroup_id, spotinst_account_data)

    assert str(exc_info.value) == ('Current user data is a map but provided '
                                   'user data is a string.')