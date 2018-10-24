"""
Functions to interact with AWS and objects to model resources
"""

import base64
import collections
import datetime
import functools
import re
import time
from contextlib import contextmanager
from pprint import pformat
from typing import Optional

import arrow
import boto3
import yaml
from botocore.exceptions import BotoCoreError, ClientError
from click import FileError
from clickclick import Action, error, info

from .exceptions import SecurityGroupNotFound
from .manaus.boto_proxy import BotoClientProxy
from .manaus.utils import extract_client_error_code
from .stack_references import check_file_exceptions


def resolve_referenced_resource(ref: dict, region: str):
    if "Stack" in ref and "LogicalId" in ref:
        cloud_formation = BotoClientProxy("cloudformation", region)
        resource = cloud_formation.describe_stack_resource(
            StackName=ref["Stack"], LogicalResourceId=ref["LogicalId"]
        )["StackResourceDetail"]
        if not is_status_complete(resource["ResourceStatus"]):
            raise ValueError(
                'Resource "{}" '
                'is not ready ("{}")'.format(
                    ref["LogicalId"], resource["ResourceStatus"]
                )
            )

        resource_id = resource["PhysicalResourceId"]

        # security_group is referenced by its name not its id
        if resource["ResourceType"] == "AWS::EC2::SecurityGroup":
            security_group = get_security_group(region, resource_id)
            return security_group.id if security_group is not None else None
        else:
            return resource_id
    elif "Stack" in ref and "Output" in ref:
        cloud_formation = BotoClientProxy("cloudformation", region)
        stack_response = cloud_formation.describe_stacks(StackName=ref["Stack"])
        stack = stack_response["Stacks"][0]
        if not is_status_complete(stack["StackStatus"]):
            raise ValueError(
                'Stack "{}" '
                'is not ready ("{}")'.format(ref["Stack"], stack["StackStatus"])
            )

        for output in stack.get("Outputs", []):
            if output["OutputKey"] == ref["Output"]:
                return output["OutputValue"]

        return None
    else:
        return ref


def is_status_complete(status: str) -> bool:
    """
    Check if stack status is running and complete.
    """
    return status in ("CREATE_COMPLETE", "UPDATE_COMPLETE")


def get_security_group(region: str, sg_name: str):
    """
    Get security group by name
    """
    ec2 = boto3.resource("ec2", region)
    try:
        # first try by tag name then by group-name (cannot be changed)
        for _filter in [
            {"Name": "tag:Name", "Values": [sg_name]},
            {"Name": "group-name", "Values": [sg_name]},
        ]:
            sec_groups = list(ec2.security_groups.filter(Filters=[_filter]))
            if sec_groups:
                # FIXME: What if we have 2 VPC, with a SG with the same name?!
                return sec_groups[0]
    except ClientError as client_error:
        error_code = extract_client_error_code(client_error)
        if error_code == "InvalidGroup.NotFound":
            return None
        elif error_code == "VPCIdNotSpecified":
            # no Default VPC, we must use the lng way...
            for security_group in ec2.security_groups.all():
                # FIXME: What if we have 2 VPC, with a SG with the same name?!
                if security_group.group_name == sg_name:
                    return security_group
            return None
        else:
            raise


def get_vpc_attribute(region: str, vpc_id: str, attribute: str):
    """
    Tries to get an attribute from vpc identified by ``vpc_id``.

    Returns ``None`` on failure.
    """
    ec2 = boto3.resource("ec2", region)
    vpc = ec2.Vpc(vpc_id)

    return getattr(vpc, attribute, None)


def encrypt(region: str, key_id: str, plaintext: str, b64encode=False):
    """
    Encrypts ``plaintext`` with the Kms key identified by ``key_id``.
    """
    kms = BotoClientProxy("kms", region)
    encrypted = kms.encrypt(KeyId=key_id, Plaintext=plaintext)["CiphertextBlob"]
    if b64encode:
        return base64.b64encode(encrypted).decode("utf-8")

    return encrypted


def list_kms_keys(region: str, details=True):
    """
    Returns a list of kms keys for a ``region``. If ``details`` is ``True``
    the returned keys will include the key's metadata
    """
    kms = BotoClientProxy("kms", region)
    keys = list(kms.list_keys()["Keys"])
    if details:
        aliases = kms.list_aliases()["Aliases"]

        for key in keys:
            key["aliases"] = [
                a["AliasName"] for a in aliases if a.get("TargetKeyId") == key["KeyId"]
            ]
            key.update(kms.describe_key(KeyId=key["KeyId"])["KeyMetadata"])

    return keys


def resolve_security_group(security_group, region: str):
    """
    Resolves a security group. security_group can be a dictionary containing
    information identifying the security group in a stack or a string with
    the security group name.
    """
    if isinstance(security_group, dict):
        security_group = resolve_referenced_resource(security_group, region)
        if not security_group:
            raise SecurityGroupNotFound(security_group)
        return security_group
    elif security_group.startswith("sg-"):
        return security_group
    else:
        security_group = get_security_group(region, security_group)
        if not security_group:
            raise SecurityGroupNotFound(security_group)
        return security_group.id


def resolve_security_groups(security_groups: list, region: str):
    """
    Resolves a list of security groups (see ``resolve_security_group``).
    """
    result = []
    for security_group in security_groups:
        result.append(resolve_security_group(security_group, region))
    return result


def parse_time(iso8601_string: str) -> float:
    """
    Parses an ISO 8601 string and returns a timestamp
    """
    try:
        dtime = arrow.get(iso8601_string).datetime
        return dtime.timestamp()
    except Exception:  # pylint: disable=locally-disabled, broad-except
        return None


def get_required_capabilities(data: dict):
    """
    Get capabilities for a given cloud formation template for the
    "create_stack" call
    """
    capabilities = []
    for _, config in data.get("Resources", {}).items():
        if config.get("Type").startswith("AWS::IAM"):
            if config.get("Properties", {}).get("RoleName"):
                capabilities.append("CAPABILITY_NAMED_IAM")
            else:
                capabilities.append("CAPABILITY_IAM")
    return capabilities


def resolve_topic_arn(region, topic_name):
    topic_arn = None
    if topic_name.startswith("arn:"):
        topic_arn = topic_name
    else:
        # resolve topic name to ARN
        sns = boto3.resource("sns", region)
        for topic in sns.topics.all():
            if topic.arn.endswith(":{}".format(topic_name)):
                topic_arn = topic.arn

    return topic_arn


@functools.total_ordering  # pylint: disable=locally-disabled, too-few-public-methods
class SenzaStackSummary:
    """
    Reference to a CloudFormation stack following senza conventions
    """

    def __init__(self, stack):
        self.stack = stack
        parts = stack["StackName"].rsplit("-", 1)
        self.name = parts[0]
        if len(parts) > 1:
            self.version = parts[1]
        else:
            self.version = ""

    def __getattr__(self, item):
        if item in self.__dict__:
            return self.__dict__[item]
        return self.stack.get(item)

    def __lt__(self, other):
        """
        Sorts two SenzaStackSummary by name and version
        """

        def key(stack_summary):
            """
            Returns a tuple so that SenzaStackSummaries can be sorted

            """
            return stack_summary.name, stack_summary.version

        return key(self) < key(other)

    def __eq__(self, other):
        """
        Checks if two SenzaStackSummary are equal by comparing the StackNames
        """
        return self.stack["StackName"] == other.stack["StackName"]


def get_stacks(
    stack_refs: list,
    region,
    all=False,  # pylint: disable=locally-disabled, redefined-builtin
    unique_only=False,
):
    """
    Gets stacks that match a list of `StackReference`.

    By default this function will only return non deleted stacks, unless `all`
    is set to true.

    Setting unique_only to True will avoid returning stacks with the same name,
    i.e. deleted stacks with the same name as other deleted or still running
    stacks.
    """
    # boto3.resource('cf')-stacks.filter() doesn't support status_filter, only StackName
    cloud_formation = BotoClientProxy("cloudformation", region)
    if all:
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
            # "DELETE_COMPLETE",
            "UPDATE_IN_PROGRESS",
            "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS",
            "UPDATE_COMPLETE",
            "UPDATE_ROLLBACK_IN_PROGRESS",
            "UPDATE_ROLLBACK_FAILED",
            "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS",
            "UPDATE_ROLLBACK_COMPLETE",
        ]
    kwargs = {"StackStatusFilter": status_filter}
    stacks = []
    while "NextToken" not in kwargs or kwargs["NextToken"]:
        results = cloud_formation.list_stacks(**kwargs)
        for stack in results["StackSummaries"]:
            if not stack_refs or matches_any(stack["StackName"], stack_refs):
                stacks.append(stack)
        kwargs["NextToken"] = results.get("NextToken")
    # After going through all stacks
    check_file_exceptions(stack_refs)

    stacks.sort(key=lambda x: x["CreationTime"], reverse=True)
    # stack names that were already yielded to avoid yielding old deleted
    # stacks whose name was reused
    stacks_yielded = set()
    output_stacks = []
    for stack in stacks:
        if stack["StackName"] not in stacks_yielded or not unique_only:
            stacks_yielded.add(stack["StackName"])
            output_stacks.append(SenzaStackSummary(stack))

    return output_stacks


def matches_any(cf_stack_name: str, stack_refs: list):
    """
    Checks if the stack name matches any of the stack references
    """

    cf_stack_name = cf_stack_name or ""  # ensure cf_stack_name is a str
    try:
        name, version = cf_stack_name.rsplit("-", 1)
    except ValueError:
        name = cf_stack_name
        version = ""
    return any(ref.matches(name, version) for ref in stack_refs)


def get_tag(tags: list, key: str, default=None):
    """
    Get value for tag from the [{"Key": key, "Value": value}] format returned
    by AWS
    """
    if isinstance(tags, list):
        found = [tag["Value"] for tag in tags if tag["Key"] == key]
        if len(found):
            return found[0]
    return default


def get_account_id():
    """
    Returns the numerical account id
    """
    conn = BotoClientProxy("iam")
    try:
        own_user = conn.get_user()["User"]
    except (BotoCoreError, ClientError):
        own_user = None
    if not own_user:
        roles = conn.list_roles()["Roles"]
        if not roles:
            users = conn.list_users()["Users"]
            if not users:
                saml = conn.list_saml_providers()["SAMLProviderList"]
                if not saml:
                    return None
                else:
                    arn = [s["Arn"] for s in saml][0]
            else:
                arn = [u["Arn"] for u in users][0]
        else:
            arn = [r["Arn"] for r in roles][0]
    else:
        arn = own_user["Arn"]
    account_id = arn.split(":")[4]
    return account_id


def get_account_alias() -> str:
    """
    Gets the human readable account alias
    """
    conn = BotoClientProxy("iam")
    return conn.list_account_aliases()["AccountAliases"][0]


class StackReference(collections.namedtuple("StackReference", "name version")):
    """
    A stack reference is a user provided reference that can match stacks
    by name and version or, in alternative, filename.
    """

    def __init__(
        self, *args, **kwargs
    ):  # pylint: disable=locally-disabled, unused-argument, super-init-not-called
        self.matched = 0
        self.possible_definition_file = self.name.endswith(
            ".yml"
        ) or self.name.endswith(".yaml")

    def raise_file_exception(self):
        """
        If it looks like a filename and didn't match anything try to open it
        to see if exists and can be opened and raise an exception if it can't
        """
        if not self.matched and self.possible_definition_file:
            try:
                with open(self.name) as potential_definition_file:
                    data = yaml.safe_load(potential_definition_file)
                assert data["SenzaInfo"]["StackName"]
            except (OSError, IOError) as error:
                raise FileError(self.name, error.strerror)
            except KeyError:
                raise ValueError("SenzaInfo.StackName missing from definition file")

    def matches(self, name: str, version: str):
        """
        Check if stack matches stack reference by name and version
        (using regular expressions). If version is not provided it will match
        all stacks that match the name.
        """
        matches_name = re.match(self.name + "$", name)
        matches_version = not self.version or re.match(self.version + "$", version)
        matches = bool(matches_name and matches_version)
        if matches:
            self.matched += 1
        return matches

    def cf_stack_name(self):
        """
        Returns the stack name based on application name and version
        """
        return "{}-{}".format(self.name, self.version) if self.version else self.name


def update_stack_from_template(region: str, template: dict, dry_run: bool):
    """
    Updates a stack from a generated template
    """
    cf = BotoClientProxy("cloudformation", region)
    del (template["Tags"])
    with Action(
        "Updating Cloud Formation stack " "{StackName}..".format_map(template)
    ) as act:
        try:
            if dry_run:
                info("**DRY-RUN** {}".format(template["NotificationARNs"]))
            else:
                cf.update_stack(**template)
        except ClientError as err:
            response = err.response
            error_info = response["Error"]
            error_message = error_info["Message"]
            if error_message == "No updates are to be performed.":
                act.ok("NO UPDATE")
            else:
                act.fatal_error("ClientError: {}".format(pformat(response)))


@contextmanager
def all_stacks_in_final_state(
    related_stacks_refs: list, region: str, timeout: Optional[int], interval: int
):
    """ Wait and check if all related stacks are in a final state before performing code block
    changes. If there is no timeout, we don't wait anything and just execute the traffic change.

    :param related_stacks_refs: Related stacks to wait
    :param region: region where stacks are present
    :param timeout: optional value of how long we should wait for the stack should be `None`
    :param interval: interval between checks using AWS CF API
    """
    if timeout is None or timeout < 1:
        yield
    else:
        wait_timeout = datetime.datetime.utcnow() + datetime.timedelta(seconds=timeout)

        all_in_final_state = False
        while not all_in_final_state and wait_timeout > datetime.datetime.utcnow():
            # assume all stacks are ready
            all_in_final_state = True
            related_stacks = get_stacks(related_stacks_refs, region)

            if not related_stacks:
                error("Stack not found!")
                exit(1)

            for related_stack in related_stacks:
                current_stack_status = related_stack.StackStatus
                if current_stack_status.endswith("_IN_PROGRESS"):
                    # some operation in progress, let's wait some time to try again
                    all_in_final_state = False
                    info(
                        "Waiting for stack {} ({}) to perform requested operation..".format(
                            related_stack.StackName, current_stack_status
                        )
                    )
                    time.sleep(interval)

        if datetime.datetime.utcnow() > wait_timeout:
            info("Timeout reached, requested operation not executed.")
            exit(1)
        else:
            yield
