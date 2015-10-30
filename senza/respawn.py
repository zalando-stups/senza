import boto3

from clickclick import Action, info


SCALING_PROCESSES_TO_SUSPEND = ['AZRebalance', 'AlarmNotification', 'ScheduledActions']


def get_instances_to_terminate(group, desired_launch_config):
    instances_to_terminate = set()
    instances_ok = set()
    for instance in group['Instances']:
        if instance['LifecycleState'] == 'InService':
            if instance['LaunchConfigurationName'] == desired_launch_config:
                instances_ok.add(instance['InstanceId'])
            else:
                instances_to_terminate.add(instance['InstanceId'])
    return instances_to_terminate, instances_ok


def do_respawn_auto_scaling_group(asg_name: str, region: str):
    asg = boto3.client('autoscaling', region)
    with Action('Suspending scaling processes for {}..'.format(asg_name)):
        asg.suspend_processes(AutoScalingGroupName=asg_name, ScalingProcesses=SCALING_PROCESSES_TO_SUSPEND)
    with Action('Resuming scaling processes for {}..'.format(asg_name)):
        asg.resume_processes(AutoScalingGroupName=asg_name)


def respawn_auto_scaling_group(asg_name: str, region: str):
    asg = boto3.client('autoscaling', region)
    result = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    groups = result['AutoScalingGroups']
    for group in groups:
        desired_launch_config = group['LaunchConfigurationName']
        instances_to_terminate, instances_ok = get_instances_to_terminate(group, desired_launch_config)
        info('{}/{} instances need to be updated in {}'.format(len(instances_to_terminate),
             len(instances_to_terminate) + len(instances_ok), asg_name))
        if instances_to_terminate:
            do_respawn_auto_scaling_group(asg_name, region)
        else:
            info('Nothing to do')
