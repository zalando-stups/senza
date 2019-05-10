import json
import re

import boto3
import botocore.exceptions
import click
import clickclick
from click import confirm
from clickclick import Action
from senza.aws import get_account_alias, get_account_id, get_security_group
from senza.utils import CROSS_STACK_POLICY_NAME
import senza.manaus.iam

from ..manaus.boto_proxy import BotoClientProxy


def prompt(variables: dict, var_name, *args, **kwargs):
    if var_name not in variables:
        if callable(kwargs.get("default")):
            # evaluate callable
            kwargs["default"] = kwargs["default"]()

        variables[var_name] = click.prompt(*args, **kwargs)
    elif "type" in kwargs:
        # ensure the variable as the right type
        type = kwargs["type"]
        variables[var_name] = type(variables[var_name])


def choice(variables: dict, var_name, *args, **kwargs):
    if var_name not in variables:
        if callable(kwargs.get("default")):
            # evaluate callable
            kwargs["default"] = kwargs["default"]()

        variables[var_name] = clickclick.choice(*args, **kwargs)
    elif "type" in kwargs:
        # ensure the variable as the right type
        type = kwargs["type"]
        variables[var_name] = type(variables[var_name])


def check_value(max_length: int, match_regex: str):
    def _value_checker(value: str):
        if len(value) <= max_length:
            if re.match(match_regex, value):
                return value
            else:
                raise click.UsageError("did not match regex {}.".format(match_regex))
        else:
            raise click.UsageError(
                "Value is too long! {} > {} chars".format(len(value), max_length)
            )

    return _value_checker


def check_security_group(sg_name, rules, region, allow_from_self=False):
    rules_missing = set()
    for rule in rules:
        rules_missing.add(rule)

    with Action("Checking security group {}..".format(sg_name)):
        sg = get_security_group(region, sg_name)
        if sg:
            for rule in sg.ip_permissions:
                # NOTE: boto object has port as string!
                for proto, port in rules:
                    if rule["IpProtocol"] == proto and rule["FromPort"] == int(port):
                        rules_missing.remove((proto, port))

    if sg:
        return rules_missing
    else:
        create_sg = click.confirm(
            "Security group {} does not exist. Do you want Senza to create it now?".format(
                sg_name
            ),
            default=True,
        )
        if create_sg:
            ec2c = BotoClientProxy("ec2", region)
            # FIXME which vpc?
            vpc = ec2c.describe_vpcs()["Vpcs"][0]
            sg = ec2c.create_security_group(
                GroupName=sg_name,
                Description="Application security group",
                VpcId=vpc["VpcId"],
            )
            ec2c.create_tags(
                Resources=[sg["GroupId"]], Tags=[{"Key": "Name", "Value": sg_name}]
            )
            ip_permissions = []
            for proto, port in rules:
                ip_permissions.append(
                    {
                        "IpProtocol": proto,
                        "FromPort": port,
                        "ToPort": port,
                        "IpRanges": [{"CidrIp": "0.0.0.0/0"}],
                    }
                )
            if allow_from_self:
                ip_permissions.append(
                    {
                        "IpProtocol": "-1",
                        "UserIdGroupPairs": [{"GroupId": sg["GroupId"]}],
                    }
                )
            ec2c.authorize_security_group_ingress(
                GroupId=sg["GroupId"], IpPermissions=ip_permissions
            )
        return set()


def get_mint_bucket_name(region: str):
    account_id = get_account_id()
    account_alias = get_account_alias()
    s3 = boto3.resource("s3")
    parts = account_alias.split("-")
    prefix = parts[0]
    bucket_name = "{}-stups-mint-{}-{}".format(prefix, account_id, region)
    bucket = s3.Bucket(bucket_name)
    try:
        bucket.load()
        return bucket.name
    except Exception:
        bucket = None
    for bucket in s3.buckets.all():
        if bucket.name.startswith("{}-stups-mint-{}-".format(prefix, account_id)):
            return bucket.name
    return bucket_name


def create_mint_read_policy_document(application_id: str, bucket_name: str, region: str):
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowMintRead",
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": [
                    "arn:aws:s3:::{}/{}/*".format(bucket_name, application_id)
                ],
            }
        ],
    }


def create_cross_stack_policy_document():
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": [
                    "cloudformation:SignalResource",
                    "cloudformation:DescribeStackResource"
                ],
                "Resource": "*"
            }
        ]
    }


def check_cross_stack_policy(iam, role_name: str):
    try:
        iam.get_role_policy(
            RoleName=role_name,
            PolicyName=CROSS_STACK_POLICY_NAME
        )
        return True
    except botocore.exceptions.ClientError:
        return False


def check_iam_role(application_id: str, bucket_name: str, region: str):
    role_name = "app-{}".format(application_id)
    with Action("Checking IAM role {}..".format(role_name)):
        iam = BotoClientProxy("iam")
        try:
            iam.get_role(RoleName=role_name)
            exists = True
        except botocore.exceptions.ClientError:
            exists = False

    assume_role_policy_document = {
        "Statement": [
            {
                "Action": "sts:AssumeRole",
                "Effect": "Allow",
                "Principal": {"Service": "ec2.amazonaws.com"},
                "Sid": "",
            }
        ],
        "Version": "2008-10-17",
    }

    create = False
    if not exists:
        create = confirm(
            "IAM role {} does not exist. "
            "Do you want Senza to create it now?".format(role_name),
            default=True,
        )
        if create:
            with Action("Creating IAM role {}..".format(role_name)):
                iam.create_role(
                    RoleName=role_name,
                    AssumeRolePolicyDocument=json.dumps(assume_role_policy_document),
                )

    attach_mint_read_policy = bucket_name is not None and (
        (not exists and create)
        or (
            exists and confirm(
                "IAM role {} already exists. ".format(role_name)
                + "Do you want Senza to overwrite the role policy?"
            )
        )
    )
    if attach_mint_read_policy:
        with Action("Updating IAM role policy of {}..".format(role_name)):
            mint_read_policy = create_mint_read_policy_document(application_id, bucket_name, region)
            iam.put_role_policy(
                RoleName=role_name,
                PolicyName=role_name,
                PolicyDocument=json.dumps(mint_read_policy),
            )

    attach_cross_stack_policy(exists, create, role_name, iam)


def find_or_create_cross_stack_policy():
    return senza.manaus.iam.find_or_create_policy(policy_name=CROSS_STACK_POLICY_NAME,
                                                  policy_document=create_cross_stack_policy_document(),
                                                  description="Required permissions for EC2 instances created by "
                                                              "Spotinst to signal CloudFormation")


def attach_cross_stack_policy(pre_existing_role, role_created, role_name, iam_client):
    if not pre_existing_role and not role_created:
        return

    cross_stack_policy_exists = False
    if pre_existing_role:
        cross_stack_policy_exists = check_cross_stack_policy(iam_client, role_name)

    if role_created or not cross_stack_policy_exists:
        with Action("Updating IAM role policy of {}..".format(role_name)):
            policy = find_or_create_cross_stack_policy()

            iam_client.attach_role_policy(
                RoleName=role_name,
                PolicyArn=policy["Arn"],
            )


def check_s3_bucket(bucket_name: str, region: str):
    s3 = boto3.resource("s3", region)
    with Action("Checking S3 bucket {}..".format(bucket_name)):
        exists = False
        try:
            s3.meta.client.head_bucket(Bucket=bucket_name)
            exists = True
        except Exception:
            pass
    if not exists:
        with Action("Creating S3 bucket {}...".format(bucket_name)):
            s3.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": region},
            )
