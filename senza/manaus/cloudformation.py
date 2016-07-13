from typing import Optional, List, Dict
from collections import OrderedDict
from datetime import datetime
import boto3


class CloudFormationStack:

    """
    A single AWS Cloudformation Stack.

    See:
    http://boto3.readthedocs.io/en/latest/reference/services/cloudformation.html
    """

    def __init__(self,
                 stack_id: str,
                 stack_name: str,
                 description: str,
                 parameters: Dict[str, str],
                 creation_time: datetime,
                 last_updated_time: Optional[datetime],
                 status: str,
                 stack_status_reason: Optional[str],
                 disable_rollback: bool,
                 notification_arns: List[str],
                 timeout_in_minutes: Optional[int],
                 capabilities: List[str],
                 outputs: Optional[List[Dict]],
                 tags: Dict[str, str]):
        self.stack_id = stack_id
        self.stack_name = stack_name
        self.description = description
        self.parameters = parameters
        self.creation_time = creation_time
        self.last_updated_time = last_updated_time
        self.status = status
        self.stack_status_reason = stack_status_reason
        self.disable_rollback = disable_rollback
        self.notification_arns = notification_arns
        self.timeout_in_minutes = timeout_in_minutes
        self.capabilities = capabilities
        self.outputs = outputs

    @classmethod
    def get_by_stack_name(cls,
                          name: str,
                          region: Optional[str]=None) -> "CloudFormationStack":
        """
        See:
        http://boto3.readthedocs.io/en/latest/reference/services/cloudformation.html#CloudFormation.Client.describe_stacks
        """
        client = boto3.client('cloudformation', region)
        stacks = client.describe_stacks(StackName=name)
        stack = stacks['Stacks'][0]  # type: dict

        stack_id = stack['StackId']
        stack_name = stack['StackName']
        description = stack['Description']
        parameters = OrderedDict([(p['ParameterKey'], p['ParameterValue'])
                                  for p in stack['Parameters']
                                  if not p.get('UsePreviousValue')])
        creation_time = stack['CreationTime']
        last_updated_time = stack.get('LastUpdatedTime')
        status = stack['StackStatus']
        stack_status_reason = stack.get('StackStatusReason')
        disable_rollback = stack['DisableRollback']
        notification_arns = stack['NotificationARNs']
        timeout_in_minutes = stack.get('TimeoutInMinutes')
        capabilities = stack['Capabilities']
        outputs = stack.get('Outputs')
        tags = OrderedDict([(t['Key'], t['Value']) for t in stack['Tags']])

        return cls(stack_id, stack_name, description, parameters,
                   creation_time, last_updated_time, status,
                   stack_status_reason, disable_rollback, notification_arns,
                   timeout_in_minutes, capabilities, outputs, tags)
