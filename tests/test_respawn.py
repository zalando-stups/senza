import copy

from unittest.mock import MagicMock
from senza.respawn import respawn_auto_scaling_group, respawn_elastigroup, respawn_stateful_elastigroup
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


def test_respawn_elastigroup_with_stateful_instances(monkeypatch):
    elastigroup_id = 'sig-xfy'
    stack_name = 'my-app-stack'
    batch_size = None

    spotinst_account = SpotInstAccountData('act-zwk', 'fake-token')

    execution_data = {
        'instances': [{
            'id': 'ssi-1abc9',
            'instanceId': 'i-abcdef123',
            'privateIp': '172.31.0.0',
            'state': 'ACTIVE'
        }, {
            'id': 'ssi-9xyz1',
            'instanceId': 'i-123defabc',
            'privateIp': '172.31.255.0',
            'state': 'ACTIVE'
        }],
        'instances_waited_for': [],
        'recycle_triggered_for': [],
    }
    def get_stateful_instances(*args):
        recycling_instances = [i for i in execution_data['instances']
                               if i['state'] == 'RECYCLING']
        for i in recycling_instances:
            i['_ticks_left'] -= 1
            if i['_ticks_left'] == 0:
                i['state'] = 'ACTIVE'
                execution_data['instances_waited_for'].append(i['id'])

        # return a snapshot of our internal state to avoid surprises
        return copy.deepcopy(execution_data['instances'])

    monkeypatch.setattr('senza.spotinst.components.elastigroup_api.get_stateful_instances', get_stateful_instances)

    def recycle_stateful_instance(gid, ssi, acc):
        assert all(i['state'] == 'ACTIVE' for i in execution_data['instances']), \
            "all instances should be in ACTIVE state before triggering recycle"

        assert any(i['id'] == ssi for i in execution_data['instances']), \
            "stateful instance must be on the list for this group".format(ssi)

        for i in execution_data['instances']:
            if i['id'] == ssi:
                i['state'] = 'RECYCLING'
                i['_ticks_left'] = 5
                execution_data['recycle_triggered_for'].append(i['id'])
                return [{'code': 200, 'message': 'OK'}]

    monkeypatch.setattr(
        'senza.spotinst.components.elastigroup_api.recycle_stateful_instance',
        recycle_stateful_instance
    )

    respawn_stateful_elastigroup(
        elastigroup_id, stack_name, batch_size, get_stateful_instances(), spotinst_account, sleep_sec=0.1
    )

    assert execution_data['instances_waited_for'] == ['ssi-1abc9', 'ssi-9xyz1']
    assert execution_data['recycle_triggered_for'] == ['ssi-1abc9', 'ssi-9xyz1']


def test_respawn_elastigroup_no_stateful_instances(monkeypatch):
    elastigroup_id = 'sig-xfy'
    stack_name = 'my-app-stack'
    region = 'my-region'
    batch_size = 35

    spotinst_account = SpotInstAccountData('act-zwk', 'fake-token')
    spotinst_account_mock = MagicMock()
    spotinst_account_mock.return_value = spotinst_account

    monkeypatch.setattr('senza.spotinst.components.elastigroup_api.get_spotinst_account_data', spotinst_account_mock)

    get_stateful_instances_output = []
    get_stateful_instances_output_mock = MagicMock()
    get_stateful_instances_output_mock.return_value = get_stateful_instances_output
    monkeypatch.setattr('senza.spotinst.components.elastigroup_api.get_stateful_instances', get_stateful_instances_output_mock)

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
