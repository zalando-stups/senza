import codecs

from unittest.mock import MagicMock
import pytest

from senza.exceptions import InvalidUserDataType
from senza.patch import patch_auto_scaling_group

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
