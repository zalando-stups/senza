
from unittest.mock import MagicMock
from senza.respawn import respawn_auto_scaling_group, respawn_elastigroup
from senza.spotinst.components.elastigroup_api import SpotInstAccountData


def test_respawn_auto_scaling_group(monkeypatch):

    inst = {'InstanceId': 'myinst-1', 'LaunchConfigurationName': 'lc-1', 'LifecycleState': 'InService'}
    group = {'LaunchConfigurationName': 'lc-2', 'Instances': [inst], 'MinSize': 1, 'MaxSize': 1, 'DesiredCapacity': 1,
             'LoadBalancerNames': ['myelb']}
    groups = {'AutoScalingGroups': [group]}
    instance_states = [{'InstanceId': 'myinst-1', 'State': 'InService'},
                       {'InstanceId': 'myinst-2', 'State': 'InService'}]
    asg = MagicMock()
    asg.describe_auto_scaling_groups.return_value = groups

    def terminate_instance(InstanceId, **kwargs):
        for i in range(len(instance_states)):
            if instance_states[i]['InstanceId'] == InstanceId:
                del instance_states[i]
                break

    asg.terminate_instance_in_auto_scaling_group = terminate_instance
    elb = MagicMock()
    elb.describe_instance_health.return_value = {'InstanceStates': instance_states}
    services = {'autoscaling': asg, 'elb': elb}

    def client(service, region):
        assert region == 'myregion'
        return services[service]
    monkeypatch.setattr('boto3.client', client)
    monkeypatch.setattr('time.sleep', lambda s: s)
    respawn_auto_scaling_group('myasg', 'myregion')


def test_respawn_auto_scaling_group_without_elb(monkeypatch):

    inst = {'InstanceId': 'myinst-1', 'LaunchConfigurationName': 'lc-1', 'LifecycleState': 'InService'}
    instances = [inst]
    group = {'AutoScalingGroupName': 'myasg',
             'LaunchConfigurationName': 'lc-2', 'Instances': instances, 'MinSize': 1, 'MaxSize': 1, 'DesiredCapacity': 1,
             'LoadBalancerNames': []}
    groups = {'AutoScalingGroups': [group]}
    asg = MagicMock()
    asg.describe_auto_scaling_groups.return_value = groups

    def update_group(**kwargs):
        instances.append({'InstanceId': 'myinst-2', 'LaunchConfigurationName': 'lc-2', 'LifecycleState': 'InService'})

    def terminate_instance(InstanceId, **kwargs):
        for i in range(len(instances)):
            if instances[i]['InstanceId'] == InstanceId:
                del instances[i]
                break

    asg.update_auto_scaling_group = update_group
    asg.terminate_instance_in_auto_scaling_group = terminate_instance
    services = {'autoscaling': asg}
    def client(service, *args):
        return services[service]
    monkeypatch.setattr('boto3.client', client)
    monkeypatch.setattr('time.sleep', lambda s: s)
    respawn_auto_scaling_group('myasg', 'myregion')


def test_respawn_elastigroup(monkeypatch):
    elastigroup_id = 'sig-xfy'
    stack_name = 'my-app-stack'
    region = 'my-region'
    batch_size = 35

    spotinst_account = SpotInstAccountData('act-zwk', 'fake-token')
    spotinst_account_mock = MagicMock()
    spotinst_account_mock.return_value = spotinst_account

    monkeypatch.setattr('senza.spotinst.components.elastigroup_api.get_spotinst_account_data', spotinst_account_mock)

    deploy_output = [{
        'id': 'deploy-1'
    }]
    deploy_output_mock = MagicMock()
    deploy_output_mock.return_value = deploy_output
    monkeypatch.setattr('senza.spotinst.components.elastigroup_api.deploy', deploy_output_mock)

    execution_data = {
        'percentage': 0,
        'runs': 0,
        'status': 'starting'
    }

    def deploy_status(*args):
        execution_data['runs'] += 1
        execution_data['percentage'] += 50
        if execution_data['percentage'] == 100:
            execution_data['status'] = 'finished'
        else:
            execution_data['status'] = 'in_progress'
        return [{
            'id': args[0],
            'status': execution_data['status'],
            'progress': {
                'value': execution_data['percentage']
            }
        }]
    monkeypatch.setattr('senza.spotinst.components.elastigroup_api.deploy_status', deploy_status)
    respawn_elastigroup(elastigroup_id, stack_name, region, batch_size)

    assert execution_data['runs'] == 2
    assert execution_data['percentage'] == 100
