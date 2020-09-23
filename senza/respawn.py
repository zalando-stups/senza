"""
Functions to scale and respawn Auto Scale Groups
"""
import collections
import time

from clickclick import Action, info

from .manaus.boto_proxy import BotoClientProxy
from .spotinst.components import elastigroup_api

SCALING_PROCESSES_TO_SUSPEND = ["AZRebalance", "AlarmNotification", "ScheduledActions"]
RUNNING_LIFECYCLE_STATES = set(["Pending", "InService", "Rebooting"])

ELASTIGROUP_TERMINATED_DEPLOY_STATUS = ["stopped", "failed"]

DEFAULT_BATCH_SIZE = 20
WAIT_FOR_ELASTIGROUP_SEC = 10


def get_auto_scaling_group(asg, asg_name: str):
    """Get boto3 Auto Scaling Group by name or raise exception"""
    result = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
    groups = result["AutoScalingGroups"]
    if not groups:
        raise Exception("Auto Scaling Group {} not found".format(asg_name))
    return groups[0]


def get_instances_to_terminate(group, desired_launch_config: str, force: bool):
    """Return set of instance IDs to terminate for given Auto Scaling Group

    Returns all instances where the launch configuration is not up-to-date"""
    instances_to_terminate = set()
    instances_ok = set()
    for instance in group["Instances"]:
        if instance["LifecycleState"] in RUNNING_LIFECYCLE_STATES:
            # NOTE: LaunchConfigurationName key might be missing (if config was deleted..)
            if (
                not force
                and instance.get("LaunchConfigurationName") == desired_launch_config
            ):
                instances_ok.add(instance["InstanceId"])
            else:
                instances_to_terminate.add(instance["InstanceId"])
    return instances_to_terminate, instances_ok


def get_instances_in_service(group, region: str):
    """Get set of instance IDs with ELB "InService" state"""
    instances_in_service = set()
    # TODO: handle auto scaling groups without any ELB
    lb_names = group["LoadBalancerNames"]
    if lb_names:
        # check ELB status
        elb = BotoClientProxy("elb", region)
        for lb_name in lb_names:
            result = elb.describe_instance_health(LoadBalancerName=lb_name)
            for instance in result["InstanceStates"]:
                if instance["State"] == "InService":
                    instances_in_service.add(instance["InstanceId"])
    else:
        # just use ASG LifecycleState
        group = get_auto_scaling_group(
            BotoClientProxy("autoscaling", region), group["AutoScalingGroupName"]
        )
        for instance in group["Instances"]:
            if instance["LifecycleState"] == "InService":
                instances_in_service.add(instance["InstanceId"])
    return instances_in_service


def scale_out(
    asg, asg_name, region: str, new_min_size, new_max_size, new_desired_capacity: int
):
    """
    Scale out the given Auto Scaling Group to the given capacity
    and wait for all instances to become "InService" in ELB
    """
    with Action("Scaling to {} instances..".format(new_desired_capacity)) as act:
        asg.update_auto_scaling_group(
            AutoScalingGroupName=asg_name,
            MinSize=new_min_size,
            MaxSize=new_max_size,
            DesiredCapacity=new_desired_capacity,
        )
        while True:
            current_group = get_auto_scaling_group(asg, asg_name)
            instances_in_service = get_instances_in_service(current_group, region)
            if len(instances_in_service) >= new_desired_capacity:
                break
            time.sleep(5)
            act.progress()
    return current_group


def terminate_instance(asg, region: str, group, instance: str):
    """
    Terminate a single EC2 instance in given Auto Scaling Group and wait for
    it to become "OutOfService"
    """

    with Action("Terminating old instance {}..".format(instance)) as act:
        asg.terminate_instance_in_auto_scaling_group(
            InstanceId=instance, ShouldDecrementDesiredCapacity=False
        )
        instances_in_service = get_instances_in_service(group, region)
        while instance in instances_in_service:
            time.sleep(2)
            act.progress()
            instances_in_service = get_instances_in_service(group, region)


def do_respawn_auto_scaling_group(
    asg_name: str, group: dict, region: str, instances_to_terminate: set, inplace: bool
):
    """
    Respawn ASG.
    """
    asg = BotoClientProxy("autoscaling", region)
    with Action("Suspending scaling processes for {}..".format(asg_name)):
        asg.suspend_processes(
            AutoScalingGroupName=asg_name, ScalingProcesses=SCALING_PROCESSES_TO_SUSPEND
        )
    extra_capacity = 0 if inplace else 1
    new_min_size = group["MinSize"] + extra_capacity
    new_max_size = group["MaxSize"] + extra_capacity
    new_desired_capacity = group["DesiredCapacity"] + extra_capacity
    # TODO: error handling (rollback in case of exception?)
    while instances_to_terminate:
        current_group = scale_out(
            asg, asg_name, region, new_min_size, new_max_size, new_desired_capacity
        )
        instance = sorted(instances_to_terminate)[0]
        terminate_instance(asg, region, current_group, instance)
        instances_to_terminate.remove(instance)

    with Action(
        "Resetting Auto Scaling Group to original capacity "
        "({MinSize}-{DesiredCapacity}-{MaxSize})..".format_map(group)
    ):
        asg.update_auto_scaling_group(
            AutoScalingGroupName=asg_name,
            MinSize=group["MinSize"],
            MaxSize=group["MaxSize"],
            DesiredCapacity=group["DesiredCapacity"],
        )

    with Action("Resuming scaling processes for {}..".format(asg_name)):
        asg.resume_processes(AutoScalingGroupName=asg_name)


def respawn_auto_scaling_group(
    asg_name: str, region: str, inplace: bool = False, force: bool = False
):
    """
    Respawn all EC2 instances in the Auto Scaling Group whose launch
    configuration is not up-to-date
    """
    asg = BotoClientProxy("autoscaling", region)
    group = get_auto_scaling_group(asg, asg_name)
    desired_launch_config = group["LaunchConfigurationName"]
    instances_to_terminate, instances_ok = get_instances_to_terminate(
        group, desired_launch_config, force
    )
    info(
        "{}/{} instances need to be updated in {}".format(
            len(instances_to_terminate),
            len(instances_to_terminate) + len(instances_ok),
            asg_name,
        )
    )
    if instances_to_terminate:
        do_respawn_auto_scaling_group(
            asg_name, group, region, instances_to_terminate, inplace
        )
    else:
        info("Nothing to do")


def respawn_elastigroup(
    elastigroup_id: str, stack_name: str, region: str, batch_size: int, batch_per_subnet: bool
):
    """
    Respawn all instances in the ElastiGroup.
    """

    spotinst_account = elastigroup_api.get_spotinst_account_data(region, stack_name)

    stateful_instances = elastigroup_api.get_stateful_instances(elastigroup_id, spotinst_account)
    if stateful_instances:
        if batch_size is not None:
            raise Exception("Batch size is not supported when respawning stateful ElastiGroups")

        respawn_stateful_elastigroup(
            elastigroup_id, stack_name, region, batch_per_subnet, stateful_instances, spotinst_account
        )
    else:
        if batch_per_subnet:
            raise Exception("Batch per subnet is not supported when respawning stateless ElastiGroups")

        respawn_stateless_elastigroup(elastigroup_id, stack_name, batch_size, spotinst_account)


def respawn_stateful_elastigroup(
    elastigroup_id: str,
    stack_name: str,
    region: str,
    batch_per_subnet: bool,
    stateful_instances: list,
    spotinst_account
):
    """
    Recycles stateful instances of the ElastiGroup.
    """

    if not stateful_elastigroup_ready(stateful_instances):
        raise Exception(
            "Stateful ElastiGroup {} is not ready: some instances are not in the ACTIVE state".format(elastigroup_id)
        )

    info(
        "Recycling {} stateful instances for ElastiGroup {} (ID {})".format(
            len(stateful_instances), stack_name, elastigroup_id
        )
    )

    if batch_per_subnet:
        instances_by_subnet = stateful_elastigroup_instances_by_subnet(region, stateful_instances)
        for subnet, subnet_instances in sorted(instances_by_subnet.items(), key=lambda item: item[0]):
            info("Recycling ALL stateful instances in subnet: {}".format(subnet))

            for instance in sorted(subnet_instances, key=lambda i: i['privateIp']):
                time.sleep(WAIT_FOR_ELASTIGROUP_SEC)
                recycle_stateful_elastigroup_instance(elastigroup_id, instance, spotinst_account)

            wait_for_stateful_elastigroup(elastigroup_id, spotinst_account)

    else:
        for instance in sorted(stateful_instances, key=lambda i: i['privateIp']):
            recycle_stateful_elastigroup_instance(elastigroup_id, instance, spotinst_account)
            wait_for_stateful_elastigroup(elastigroup_id, spotinst_account)


def stateful_elastigroup_instances_by_subnet(region: str, stateful_instances: list):
    instances_by_subnet = collections.defaultdict(list)
    instances_by_ec2_id = {i['instanceId']: i for i in stateful_instances}

    ec2 = BotoClientProxy("ec2", region)
    ec2_instances = ec2.describe_instances(InstanceIds=list(instances_by_ec2_id.keys()))
    for r in ec2_instances['Reservations']:
        for i in r['Instances']:
            subnet = "{} | {}".format(
                i['Placement']['AvailabilityZone'], i['SubnetId']
            )
            instance = instances_by_ec2_id[i['InstanceId']]
            instances_by_subnet[subnet].append(instance)

    return instances_by_subnet


def stateful_elastigroup_ready(stateful_instances: list):
    return all(i['state'] == elastigroup_api.STATEFUL_STATE_ACTIVE for i in stateful_instances)


def wait_for_stateful_elastigroup(elastigroup_id: str, spotinst_account):
    """
    Waits for all stateful instances of the ElastiGroup to be in the ACTIVE state.
    """
    with Action("Waiting for all stateful instances to be in the ACTIVE state") as act:
        while True:
            time.sleep(WAIT_FOR_ELASTIGROUP_SEC)
            act.progress()
            stateful_instances = elastigroup_api.get_stateful_instances(elastigroup_id, spotinst_account)
            if stateful_elastigroup_ready(stateful_instances):
                break


def recycle_stateful_elastigroup_instance(elastigroup_id: str, instance: dict, spotinst_account):
    info(
        "Recycling stateful instance {} ({} | {})".format(
            instance['id'], instance['instanceId'], instance['privateIp']
        )
    )
    elastigroup_api.recycle_stateful_instance(elastigroup_id, instance['id'], spotinst_account)


def respawn_stateless_elastigroup(
    elastigroup_id: str, stack_name: str, batch_size: int, spotinst_account
):
    """
    Start a deployment of the ElastiGroup and wait for it to complete.
    """

    if batch_size is None or batch_size < 1:
        batch_size = DEFAULT_BATCH_SIZE

    info(
        "Redeploying instances for ElastiGroup {} (ID {})".format(
            stack_name, elastigroup_id
        )
    )

    deploy_output = elastigroup_api.deploy(
        batch_size=batch_size,
        grace_period=600,
        elastigroup_id=elastigroup_id,
        spotinst_account_data=spotinst_account,
    )

    deploy_count = len(deploy_output)
    deploys_finished = 0
    with Action(
        "Waiting for deploy to complete. Total of {} deploys".format(deploy_count)
    ) as act:
        while True:
            for deploy in deploy_output:
                deploy_status = elastigroup_api.deploy_status(
                    deploy["id"], elastigroup_id, spotinst_account
                )
                for ds in deploy_status:
                    if ds["id"] == deploy["id"]:
                        if (
                            ds["progress"]["value"] >= 100
                            or ds["status"].lower()
                            in ELASTIGROUP_TERMINATED_DEPLOY_STATUS
                        ):
                            deploys_finished += 1
                            info(
                                "Deploy {} finished with status {}".format(
                                    ds["id"], ds["status"]
                                )
                            )

            if deploys_finished == deploy_count:
                break
            time.sleep(2)
            act.progress()
