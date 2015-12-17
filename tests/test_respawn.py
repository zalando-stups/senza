
from unittest.mock import MagicMock
from senza.respawn import respawn_auto_scaling_group

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

