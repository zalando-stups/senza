"""
CloudFormation_ related classes and functions.

For more information see the `CloudFormation documentation`_ and the
`boto3 documentation`_

.. _CloudFormation: https://aws.amazon.com/cloudformation/
.. _CloudFormation documentation: https://aws.amazon.com/documentation/cloudformation/
.. _boto3 documentation:
    http://boto3.readthedocs.io/en/latest/reference/services/cloudformation.html
"""

import json
from collections import OrderedDict
from datetime import datetime
from enum import Enum
from typing import Dict, Iterator, List, Optional

from botocore.exceptions import ClientError

from .boto_proxy import BotoClientProxy
from .exceptions import StackNotFound, StackNotUpdated
from .route53 import Route53


class ResourceType(str, Enum):
    """
    Possible AWS resource types (still incomplete)
    """
    route53_record_set = 'AWS::Route53::RecordSet'


class CloudFormationStack:

    """
    A single AWS Cloudformation Stack.

    See:
    http://boto3.readthedocs.io/en/latest/reference/services/cloudformation.html
    """

    def __init__(self,
                 stack_id: str,
                 name: str,
                 description: Optional[str],
                 parameters: Dict[str, str],
                 creation_time: datetime,
                 last_updated_time: Optional[datetime],
                 status: str,
                 stack_status_reason: Optional[str],
                 disable_rollback: bool,
                 notification_arns: List[str],
                 timeout_in_minutes: Optional[int],
                 capabilities: Optional[List[str]],
                 outputs: Optional[List[Dict]],
                 tags: Dict[str, str],
                 *,
                 region: Optional[str]):
        self.stack_id = stack_id
        self.name = name
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
        self.tags = tags

        self.region = region

        self.__template = None

    def __repr__(self):
        return "<CloudFormationStack: {name}>".format_map(vars(self))

    @classmethod
    def from_boto_dict(cls,
                       stack: Dict,
                       region: Optional[str]=None) -> "CloudFormationStack":
        """
        Converts the dict returned by ``boto3.client.describe_stacks`` to a
        ``CloudFormationStack`` instance.
        """
        stack_id = stack['StackId']
        name = stack['StackName']
        description = stack.get('Description')
        parameters = OrderedDict([(p['ParameterKey'], p['ParameterValue'])
                                  for p in stack.get('Parameters', [])
                                  if not p.get('UsePreviousValue')])
        creation_time = stack['CreationTime']
        last_updated_time = stack.get('LastUpdatedTime')
        status = stack['StackStatus']
        stack_status_reason = stack.get('StackStatusReason')
        disable_rollback = stack['DisableRollback']
        notification_arns = stack['NotificationARNs']
        timeout_in_minutes = stack.get('TimeoutInMinutes')
        capabilities = stack.get('Capabilities')
        outputs = stack.get('Outputs')
        tags = OrderedDict([(t['Key'], t['Value']) for t in stack['Tags']])

        return cls(stack_id, name, description, parameters,
                   creation_time, last_updated_time, status,
                   stack_status_reason, disable_rollback, notification_arns,
                   timeout_in_minutes, capabilities, outputs, tags,
                   region=region)

    @classmethod
    def get_by_stack_name(cls,
                          name: str,
                          region: Optional[str]=None) -> "CloudFormationStack":
        """
        See:
        http://boto3.readthedocs.io/en/latest/reference/services/cloudformation.html#CloudFormation.Client.describe_stacks
        """
        client = BotoClientProxy('cloudformation', region)

        try:
            stacks = client.describe_stacks(StackName=name)
        except ClientError as err:
            response = err.response
            error_info = response['Error']
            error_message = error_info['Message']
            # This is not very resilient way to do this but boto API doesn't
            # provide a better way.
            if error_message == 'Stack with id {name} does not exist'.format(name=name):
                raise StackNotFound(name)
            else:
                raise
        stack = stacks['Stacks'][0]  # type: dict

        return cls.from_boto_dict(stack, region)

    @property
    def resources(self) -> Iterator:
        """
        Returns the stack resources as Manaus Objects
        """
        client = BotoClientProxy('cloudformation', self.region)
        response = client.list_stack_resources(StackName=self.stack_id)
        resources = response['StackResourceSummaries']  # type: List[Dict]
        for resource in resources:
            resource_type = resource["ResourceType"]
            if resource_type == ResourceType.route53_record_set:
                physical_resource_id = resource.get('PhysicalResourceId')
                if physical_resource_id is None:
                    # if there is no Physical Resource Id we can't fetch the
                    # record
                    continue
                records = Route53.get_records(name=resource['PhysicalResourceId'])
                for record in records:
                    if (record.set_identifier is None or
                            record.set_identifier == self.name):
                        yield record
            else:  # pragma: no cover
                # TODO implement the other resource types
                # Ignore resources that are still not implemented in manaus
                pass

    @property
    def template(self) -> Dict:
        """
        Fetches the template json for the stack and caches it locally - reset
        with CloudFormationStack.reset().
        """
        if self.__template is None:
            client = BotoClientProxy('cloudformation', self.region)
            response = client.get_template(StackName=self.name)
            self.__template = response['TemplateBody']
        return self.__template

    def reset(self):
        """
        Resets the locally stored template
        :return:
        """
        self.__template = None

    def update(self):
        """
        Sends the current template to CloudFormation to update the stack
        """
        client = BotoClientProxy('cloudformation', self.region)
        parameters = [{'ParameterKey': key, 'ParameterValue': value}
                      for key, value in self.parameters.items()]
        try:
            client.update_stack(StackName=self.name,
                                TemplateBody=json.dumps(self.template),
                                Parameters=parameters,
                                Capabilities=self.capabilities)
        except ClientError as err:
            response = err.response
            error_info = response['Error']
            error_message = error_info['Message']
            if error_message == 'No updates are to be performed.':
                raise StackNotUpdated(self.name)
            else:
                raise

    def delete(self):
        """
        Delete the CloudFormation stack
        """
        client = BotoClientProxy('cloudformation', self.region)
        client.delete_stack(StackName=self.stack_id)


class CloudFormation:
    """
    Represents the CloudFormation service.

    See:
    http://boto3.readthedocs.io/en/latest/reference/services/cloudformation.html
    """
    def __init__(self, region: Optional[str]=None):
        self.region = region

    def get_stacks(self,
                   all_stacks: bool=False) -> Iterator[CloudFormationStack]:
        """
        Gets CloudFormation stacks from aws. If all_stacks is ``True`` it will
        also include deleted stacks
        """
        client = BotoClientProxy('cloudformation', self.region)
        if all_stacks:
            status_filter = []
        else:
            # status_filter = [st for st in cf.valid_states if st != 'DELETE_COMPLETE']
            status_filter = [
                "CREATE_IN_PROGRESS",
                "CREATE_FAILED",
                "CREATE_COMPLETE",
                "ROLLBACK_IN_PROGRESS",
                "ROLLBACK_FAILED",
                "ROLLBACK_COMPLETE",
                "DELETE_IN_PROGRESS",
                "DELETE_FAILED",
                "UPDATE_IN_PROGRESS",
                "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
                "UPDATE_COMPLETE",
                "UPDATE_ROLLBACK_IN_PROGRESS",
                "UPDATE_ROLLBACK_FAILED",
                "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS",
                "UPDATE_ROLLBACK_COMPLETE"
            ]

        kwargs = {'StackStatusFilter': status_filter}
        while 'NextToken' not in kwargs or kwargs['NextToken']:
            results = client.list_stacks(**kwargs)
            for stack in results['StackSummaries']:
                stack_id = stack['StackId']
                yield CloudFormationStack.get_by_stack_name(stack_id,
                                                            region=self.region)
            kwargs['NextToken'] = results.get('NextToken')
