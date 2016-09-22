from collections import OrderedDict
from typing import Dict, Iterator, List, Optional

import boto3

from .exceptions import VPCError


class EC2VPC:

    """
    See:
    http://boto3.readthedocs.io/en/latest/reference/services/ec2.html#vpc
    """

    def __init__(self,
                 vpc_id: str,
                 is_default: bool,
                 tags: Optional[List[Dict[str, str]]]):
        self.vpc_id = vpc_id
        self.is_default = is_default
        tags = tags or []  # type: List[Dict[str, str]]
        self.tags = OrderedDict([(t['Key'], t['Value']) for t in tags])  # type: Dict[str, str]

        self.name = self.tags.get('Name', self.vpc_id)

    def __str__(self):
        return '{name} ({vpc_id})'.format_map(vars(self))

    def __repr__(self):
        return '<EC2VPC: {name} ({vpc_id})>'.format_map(vars(self))

    @classmethod
    def from_boto_vpc(cls, vpc) -> "EC2VPC":
        """
        Converts an ec2.VPC as returned by resource.vpcs.all()

        See:
        http://boto3.readthedocs.io/en/latest/reference/services/ec2.html#vpc
        """

        return cls(vpc.vpc_id, vpc.is_default, vpc.tags)


class EC2:

    def __init__(self, region: str):
        self.region = region

    def get_all_vpcs(self) -> Iterator[EC2VPC]:
        """
        Get all VPCs from the account
        """
        resource = boto3.resource('ec2', self.region)

        for vpc in resource.vpcs.all():
            yield EC2VPC.from_boto_vpc(vpc)

    def get_default_vpc(self) -> EC2VPC:
        """
        Get one VPC from the account, either the default or, if only one
        exists, that one.
        """
        resource = boto3.resource('ec2', self.region)

        number_of_vpcs = 0
        # We shouldn't use the list with .all() because it has internal paging!
        for vpc_number, vpc in enumerate(resource.vpcs.all(), start=1):
            number_of_vpcs = vpc_number

            if vpc.is_default:
                return EC2VPC.from_boto_vpc(vpc)

            if vpc_number == 1:
                first_vpc = vpc

        if number_of_vpcs == 0:
            raise VPCError("Can't find any VPC!", number_of_vpcs)
        elif number_of_vpcs == 1:
            # Use the only one VPC if it's not the default VPC found
            return EC2VPC.from_boto_vpc(first_vpc)
        else:
            raise VPCError("Multiple VPCs are only supported if one "
                           "VPC is the default VPC (IsDefault=true)!",
                           number_of_vpcs)
