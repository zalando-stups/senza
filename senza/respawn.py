import boto3
import time

from clickclick import Action, info


SCALING_PROCESSES_TO_SUSPEND = ['AZRebalance', 'AlarmNotification', 'ScheduledActions']
RUNNING_LIFECYCLE_STATES = set(['Pending', 'InService', 'Rebooting'])


def get_auto_scaling_group(asg, asg_name: str):
    result = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    groups = result['AutoScalingGroups']
    if not groups:
        raise Exception('Auto Scaling Group {} not found'.format(asg_name))
    return groups[0]


def get_instances_to_terminate(group, desired_launch_config):
    instances_to_terminate = set()
    instances_ok = set()
    for instance in group['Instances']:
        if instance['LifecycleState'] in RUNNING_LIFECYCLE_STATES:
            # NOTE: LaunchConfigurationName key might be missing (if config was deleted..)
            if instance.get('LaunchConfigurationName') == desired_launch_config:
                instances_ok.add(instance['InstanceId'])
            else:
                instances_to_terminate.add(instance['InstanceId'])
    return instances_to_terminate, instances_ok


def get_instances_in_service(group, region):
    elb = boto3.client('elb')
    instances_in_service = set()
    # TODO: handle auto scaling groups without any ELB
    for lb_name in group['LoadBalancerNames']:
        result = elb.describe_instance_health(LoadBalancerName=lb_name)
        for instance in result['InstanceStates']:
            if instance['State'] == 'InService':
                instances_in_service.add(instance['InstanceId'])
    return instances_in_service


def do_respawn_auto_scaling_group(asg_name: str, group: dict, region: str,
                                  instances_to_terminate: set, instances_ok: set):
    asg = boto3.client('autoscaling', region)
    with Action('Suspending scaling processes for {}..'.format(asg_name)):
        asg.suspend_processes(AutoScalingGroupName=asg_name, ScalingProcesses=SCALING_PROCESSES_TO_SUSPEND)
    new_min_size = group['MinSize'] + 1
    new_max_size = group['MaxSize'] + 1
    new_desired_capacity = group['DesiredCapacity'] + 1
    asg.update_auto_scaling_group(AutoScalingGroupName=asg_name,
                                  MinSize=new_min_size,
                                  MaxSize=new_max_size,
                                  DesiredCapacity=new_desired_capacity)
    # TODO: error handling (rollback in case of exception?)
    while instances_to_terminate:
        with Action('Scaling to {} instances..'.format(new_desired_capacity)) as act:
            while True:
                current_group = get_auto_scaling_group(asg, asg_name)
                instances_in_service = get_instances_in_service(current_group, region)
                if len(instances_in_service) >= new_desired_capacity:
                    break
                time.sleep(5)
                act.progress()
        instance = sorted(instances_to_terminate)[0]
        with Action('Terminating old instance {}..'.format(instance)) as act:
            asg.terminate_instance_in_auto_scaling_group(InstanceId=instance, ShouldDecrementDesiredCapacity=False)
            instances_in_service = get_instances_in_service(current_group, region)
            while instance in instances_in_service:
                time.sleep(2)
                act.progress()
                instances_in_service = get_instances_in_service(current_group, region)
            instances_to_terminate.remove(instance)

    with Action('Resetting Auto Scaling Group to original capacity ({}-{}-{})..'.format(
                group['MinSize'], group['DesiredCapacity'], group['MaxSize'])):
        asg.update_auto_scaling_group(AutoScalingGroupName=asg_name,
                                      MinSize=group['MinSize'],
                                      MaxSize=group['MaxSize'],
                                      DesiredCapacity=group['DesiredCapacity'])

    with Action('Resuming scaling processes for {}..'.format(asg_name)):
        asg.resume_processes(AutoScalingGroupName=asg_name)


def respawn_auto_scaling_group(asg_name: str, region: str):
    asg = boto3.client('autoscaling', region)
    group = get_auto_scaling_group(asg, asg_name)
    desired_launch_config = group['LaunchConfigurationName']
    instances_to_terminate, instances_ok = get_instances_to_terminate(group, desired_launch_config)
    info('{}/{} instances need to be updated in {}'.format(len(instances_to_terminate),
         len(instances_to_terminate) + len(instances_ok), asg_name))
    if instances_to_terminate:
        do_respawn_auto_scaling_group(asg_name, group, region, instances_to_terminate, instances_ok)
    else:
        info('Nothing to do')
