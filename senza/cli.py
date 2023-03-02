#!/usr/bin/env python3
import base64
import calendar
import collections
import datetime
import ipaddress
import json
import os
import re
import sys
import time
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen

import boto3
import click
import senza.stups.taupage as taupage
import requests
import yaml
import senza.respawn as respawn

from botocore.exceptions import ClientError
from clickclick import (
    Action,
    FloatRange,
    OutputFormat,
    choice,
    error,
    fatal_error,
    info,
    ok,
)
from clickclick.console import print_table

from senza.components.elastigroup import ELASTIGROUP_RESOURCE_TYPE
from .spotinst.components import elastigroup_api
from .arguments import (
    json_output_option,
    output_option,
    parameter_file_option,
    region_option,
    stacktrace_visible_option,
    watch_option,
    watchrefresh_option,
    field_option,
    get_region
)
from .aws import (
    StackReference,
    get_required_capabilities,
    get_stacks,
    get_tag,
    matches_any,
    parse_time,
    resolve_topic_arn,
    update_stack_from_template,
    all_stacks_in_final_state,
)
from .components import evaluate_template, get_component
from .definitions import AccountArguments
from .error_handling import HandleExceptions
from .exceptions import InvalidDefinition, InvalidParameterFile
from .manaus.boto_proxy import BotoClientProxy
from .manaus.cloudformation import CloudFormation
from .manaus.exceptions import VPCError
from .manaus.route53 import Route53, Route53Record
from .manaus.utils import extract_client_error_code
from .patch import patch_auto_scaling_group, patch_elastigroup
from .stups.piu import Piu
from .subcommands.config import cmd_config
from .subcommands.root import cli
from .templates import get_template_description, get_templates
from .traffic import (
    change_version_traffic,
    get_records,
    print_version_traffic,
    resolve_to_ip_addresses,
)
from .utils import (
    camel_case_to_underscore,
    ensure_keys,
    named_value,
    pystache_render,
    get_load_balancer_name,
)

STYLES = {
    "RUNNING": {"fg": "green"},
    "TERMINATED": {"fg": "red"},
    "DELETE_COMPLETE": {"fg": "red"},
    "DELETE_FAILED": {"fg": "red"},
    "ROLLBACK_COMPLETE": {"fg": "red"},
    "CREATE_COMPLETE": {"fg": "green"},
    "CREATE_FAILED": {"fg": "red"},
    "PENDING": {"fg": "yellow", "bold": True},
    "CREATE_IN_PROGRESS": {"fg": "yellow", "bold": True},
    "DELETE_IN_PROGRESS": {"fg": "red", "bold": True},
    "STOPPING": {"fg": "red"},
    "STOPPED": {"fg": "red", "bold": True},
    "SHUTTING_DOWN": {"fg": "red", "bold": True},
    "ROLLBACK_IN_PROGRESS": {"fg": "red", "bold": True},
    "ROLLBACK_FAILED": {"fg": "red"},
    "UPDATE_COMPLETE": {"fg": "green"},
    "UPDATE_ROLLBACK_IN_PROGRESS": {"fg": "red", "bold": True},
    "UPDATE_IN_PROGRESS": {"fg": "yellow", "bold": True},
    "UPDATE_ROLLBACK_COMPLETE_CLEANUP_IN_PROGRESS": {"fg": "red", "bold": True},
    "UPDATE_COMPLETE_CLEANUP_IN_PROGRESS": {"fg": "yellow", "bold": True},
    "UPDATE_FAILED": {"fg": "red"},
    "UPDATE_ROLLBACK_COMPLETE": {"fg": "red"},
    "IN_SERVICE": {"fg": "green"},
    "HEALTHY": {"fg": "green"},
    "OUT_OF_SERVICE": {"fg": "red"},
    "OK": {"fg": "green"},
    "ERROR": {"fg": "red"},
}

TITLES = {
    "creation_time": "Created",
    "LogicalResourceId": "Resource ID",
    "launch_time": "Launched",
    "ResourceStatus": "Status",
    "ResourceStatusReason": "Status Reason",
    "lb_status": "LB Status",
    "private_ip": "Private IP",
    "public_ip": "Public IP",
    "resource_id": "Resource ID",
    "instance_id": "Instance ID",
    "version": "Ver.",
    "total_instances": "Inst.#",
    "running_instances": "Running",
    "docker_source": "Docker Image Source",
    "healthy_instances": "Healthy",
    "http_status": "HTTP",
    "main_dns": "Main DNS",
    "id": "ID",
    "ImageId": "Image ID",
    "OwnerId": "Owner",
    "healthy_hosts": "Healthy #",
    "requests_per_sec": "Req./s",
    "4xx_percentage": "4xx %",
    "5xx_percentage": "5xx %",
    "latency_ms": "Latency (ms)",
}

MAX_COLUMN_WIDTHS = {"description": 50, "stacks": 20, "ResourceStatusReason": 50}

SENZA_KMS_PREFIX = "senza:kms:"

AUTO_SCALING_GROUP_TYPE = "AWS::AutoScaling::AutoScalingGroup"

VALID_AUTO_SCALING_GROUPS = [AUTO_SCALING_GROUP_TYPE, ELASTIGROUP_RESOURCE_TYPE]


def filter_output_columns(output_columns, filter_columns):
    """
    Filters a list of columns and only keeps those present in a list of allowed columns.
    Returns original list of columns if no allowed columns specified.

    :param output_columns: a column list to filter
    :param filter_columns: a list of allowed columns
    :return: a filtered list of columns
    """
    if filter_columns:
        return [column for column in output_columns if column in filter_columns]

    return output_columns


def print_json(data, output=None):
    if output == "yaml":
        parsed_data = yaml.safe_load(data)
        print(yaml.safe_dump(parsed_data, indent=4, default_flow_style=False))
    else:
        print(data)


class DefinitionParamType(click.ParamType):
    name = "definition"

    def convert(self, value, param, ctx):
        if isinstance(value, str):
            try:
                url = (
                    value
                    if "://" in value
                    else "file://{}".format(quote(os.path.abspath(value)))
                )
                # if '://' not in value:
                #     url = 'file://{}'.format(quote(os.path.abspath(value)))

                response = urlopen(url)
                try:
                    data = yaml.safe_load(response.read())
                except yaml.YAMLError as e:
                    raise InvalidDefinition(path=value, reason=str(e))
            except URLError:
                self.fail('"{}" not found'.format(value), param, ctx)
        else:
            data = value

        if "SenzaInfo" not in data:
            self.fail(
                '"SenzaInfo" entry is missing in ' 'YAML file "{}"'.format(value),
                param,
                ctx,
            )
        return data


class KeyValParamType(click.ParamType):
    name = "key_val"

    def convert(self, value, param, ctx):
        if isinstance(value, str):
            try:
                key, val = value.split("=", 1)
            except Exception:
                self.fail(
                    'invalid key value parameter "{}" (must be KEY=VAL)'.format(value)
                )
            key_val = (key, val)
        else:
            key_val = value
        return key_val


def validate_version(ctx, param, value):
    if not VERSION_PATTERN.match(value):
        raise click.BadParameter(
            'Version must satisfy regular expression pattern "[a-zA-Z0-9]+"'
        )
    return value


def watching(w: bool, watch: int):
    if w and not watch:
        watch = 2
    if watch:
        click.clear()
    yield 0
    if watch:
        while True:
            time.sleep(watch)
            click.clear()
            yield 0


# from AWS docs:
# Stack name must contain only alphanumeric characters (case sensitive)
# and start with an alpha character. Maximum length of the name is 255 characters.
STACK_NAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9-]*$")
VERSION_PATTERN = re.compile(r"^[a-zA-Z0-9]+$")

DEFINITION = DefinitionParamType()

KEY_VAL = KeyValParamType()

BASE_TEMPLATE = {"AWSTemplateFormatVersion": "2010-09-09"}


def decrypt_parameters(definition, region):
    """
    Searches for encrypted values in the SenzaInfo properties and decrypts them.
    """
    try:
        senza_info = definition["Mappings"]["Senza"]["Info"]
    except KeyError:
        return definition

    for key in senza_info:
        if str(senza_info[key]).startswith(SENZA_KMS_PREFIX):
            senza_info[key] = decrypt_kms(senza_info[key], region)

    return definition


def decrypt_kms(val, region):
    """
    Decrypts KMS encrypted values. KMS encrypted values have the prefix 'senza:kms:'
    """
    ciphertext_blob = val[len(SENZA_KMS_PREFIX):]
    ciphertext_blob = base64.b64decode(ciphertext_blob)
    kms_client = boto3.client(service_name="kms", region_name=region)
    response = kms_client.decrypt(CiphertextBlob=ciphertext_blob)

    return str(response["Plaintext"], "UTF-8")


def evaluate(definition, args, account_info, force: bool):
    # extract Senza* meta information
    info = definition.pop("SenzaInfo")
    info["StackVersion"] = args.version
    # replace Arguments and AccountInfo Variables in info section
    info = yaml.safe_load(
        evaluate_template(yaml.dump(info), {}, {}, args, account_info)
    )

    # add info as mappings
    # http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/mappings-section-structure.html
    definition = ensure_keys(definition, "Mappings", "Senza", "Info")
    definition["Mappings"]["Senza"]["Info"] = info

    template = yaml.dump(definition, default_flow_style=False)
    definition = evaluate_template(template, info, [], args, account_info)
    definition = yaml.safe_load(definition)
    definition = decrypt_parameters(definition, args.region)

    components = definition.pop("SenzaComponents", [])

    # merge base template with definition
    BASE_TEMPLATE.update(definition)
    definition = BASE_TEMPLATE

    # evaluate all components
    for component in components:
        componentname, configuration = named_value(component)
        configuration["Name"] = componentname

        componenttype = configuration["Type"]
        componentfn = get_component(componenttype)

        if not componentfn:
            raise click.UsageError(
                'Component "{}" does not exist'.format(componenttype)
            )

        definition = componentfn(
            definition, configuration, args, info, force, account_info
        )

    # throw executed template to templating engine and provide all information for substitutions
    template = yaml.dump(definition, default_flow_style=False)
    definition = evaluate_template(template, info, components, args, account_info)
    definition = yaml.safe_load(definition)

    return definition


class TemplateArguments:
    def __init__(self, **kwargs):
        for key, val in kwargs.items():
            setattr(self, key, val)


def parse_args(input, region, version, parameter, account_info):
    paras = {}
    defaults = collections.OrderedDict()
    parameterlist = []

    # process positional parameters first
    seen_keyword = False
    for i, param in enumerate(input["SenzaInfo"].get("Parameters", [])):
        for key, config in param.items():
            parameterlist.append(key)
            # collect all allowed keys and default values regardless
            paras[key] = None
            defaults[key] = config.get("Default", None)
            if defaults[key] is not None:
                defaults[key] = pystache_render(
                    str(defaults[key]), {"AccountInfo": account_info}
                )
            if i < len(parameter):
                if "=" in parameter[i]:
                    seen_keyword = True
                else:
                    if seen_keyword:
                        raise click.UsageError(
                            "Positional parameters must not follow keywords."
                        )
                    paras[key] = parameter[i]

    if len(paras) < len(parameter):
        raise click.UsageError(
            'Too many parameters given. Need only: "{}"'.format(" ".join(parameterlist))
        )

    # process keyword parameters separately, if any
    if seen_keyword:
        for param in parameter:
            if "=" in param:
                key, value = param.split("=", 1)  # split only on first =
                if key not in paras:
                    raise click.UsageError(
                        'Unrecognized keyword parameter: "{}"'.format(key)
                    )
                if paras[key] is not None:
                    raise click.UsageError(
                        'Parameter specified multiple times: "{}"'.format(key)
                    )
                paras[key] = value

    # finally, make sure every parameter got a value assigned, using defaults if given
    for key, defval in defaults.items():
        if not paras[key] and paras[key] != "":
            paras[key] = defval
        if paras[key] is None:
            raise click.UsageError(
                'Missing parameter "{}". Need: "{}"'.format(
                    key, " ".join(parameterlist)
                )
            )

    args = TemplateArguments(region=region, version=version, **paras)
    return args


def read_parameter_file(parameter_file):
    paras = []

    try:
        url = (
            parameter_file
            if "://" in parameter_file
            else "file://{}".format(quote(os.path.abspath(parameter_file)))
        )

        response = urlopen(url)
    except URLError:
        raise click.UsageError('Can\'t read parameter file "{}"'.format(parameter_file))

    try:
        cfg = yaml.safe_load(response.read())
        if cfg is None:
            raise InvalidParameterFile(parameter_file, "Parameter file is empty")
        for key, val in cfg.items():
            paras.append("{}={}".format(key, val))
    except yaml.YAMLError as e:
        raise click.UsageError("Error {}".format(e))

    return tuple(paras)


def check_credentials(region):
    iam = BotoClientProxy("iam")
    return iam.list_account_aliases()


def get_stack_refs(refs: list):
    """
    Converts a list of strings in a list of StackReferences
    """

    refs = list(refs)
    refs.reverse()
    stack_refs = []
    last_stack = None
    while refs:
        ref = refs.pop()

        if last_stack is not None and re.compile(r"v[0-9][a-zA-Z0-9-]*$").match(ref):
            stack_refs.append(StackReference(last_stack, ref))
        else:
            try:
                with open(ref) as fd:
                    try:
                        data = yaml.safe_load(fd)
                    except yaml.YAMLError as e:
                        raise InvalidDefinition(path=ref, reason=str(e))

                try:
                    ref = data["SenzaInfo"]["StackName"]
                except KeyError:
                    raise InvalidDefinition(
                        path=ref, reason="SenzaInfo is missing " "or invalid"
                    )
                except TypeError:
                    raise InvalidDefinition(path=ref, reason="Invalid SenzaInfo")
            except (OSError, IOError):
                # It's still possible that the ref is a regex
                pass

            if refs:
                version = refs.pop()
            else:
                version = None
            stack_refs.append(StackReference(ref, version))
            last_stack = ref
    return stack_refs


def all_with_version(stack_refs: list):
    """
    Checks if all stackreferences have versions
    """
    for ref in stack_refs:
        if not ref.version:
            return False
    return True


@cli.command("list")
@region_option
@output_option
@watch_option
@watchrefresh_option
@click.option("--all", is_flag=True, help="Show all stacks, including deleted ones")
@field_option
@click.argument("stack_ref", nargs=-1)
@stacktrace_visible_option
def list_stacks(region, stack_ref, all, output, field, w, watch):
    """List Cloud Formation stacks"""

    check_credentials(region)

    stack_refs = get_stack_refs(stack_ref)

    for _ in watching(w, watch):
        rows = []
        for stack in get_stacks(stack_refs, region, all=all):
            rows.append(
                {
                    "stack_name": stack.name,
                    "version": stack.version,
                    "status": stack.StackStatus,
                    "creation_time": calendar.timegm(stack.CreationTime.timetuple()),
                    "description": stack.TemplateDescription,
                }
            )

        rows.sort(key=lambda x: (x["stack_name"], x["version"]))

        with OutputFormat(output):
            columns = filter_output_columns(
                ["stack_name", "version", "status", "creation_time", "description"],
                field,
            )
            print_table(columns, rows, styles=STYLES, titles=TITLES)


def get_application_load_balancer_metrics(cloudwatch, alb_id, start, now):
    alb_metrics = {
        "TargetResponseTime": "Average",
        "RequestCount": "Sum",
        "HTTPCode_Target_5XX_Count": "Sum",
        "HTTPCode_Target_4XX_Count": "Sum",
    }
    row = {}
    data = {}
    for k, v in alb_metrics.items():
        res = cloudwatch.get_metric_statistics(
            Namespace="AWS/ApplicationELB",
            MetricName=k,
            Dimensions=[{"Name": "LoadBalancer", "Value": alb_id}],
            StartTime=start,
            EndTime=now,
            Period=60,
            Statistics=[v],
        )
        # NOTE: we get the most recent two (!) datapoints as the newest point might be incomplete
        most_recent = sorted(res["Datapoints"], key=lambda x: x["Timestamp"])[-2:]
        if most_recent:
            data[(k, v)] = most_recent[0][v]
        else:
            data[(k, v)] = None
    if data[("RequestCount", "Sum")] is not None:
        requests_per_min = data[("RequestCount", "Sum")]
        row["requests_per_sec"] = round(requests_per_min / 60, 2)
    else:
        requests_per_min = 0
    if data[("HTTPCode_Target_4XX_Count", "Sum")] is not None:
        row["4xx_percentage"] = round(
            (data[("HTTPCode_Target_4XX_Count", "Sum")]) / (requests_per_min + 0.0001),
            2,
        )
    if data[("HTTPCode_Target_5XX_Count", "Sum")] is not None:
        row["5xx_percentage"] = round(
            (data[("HTTPCode_Target_5XX_Count", "Sum")]) / (requests_per_min + 0.0001),
            2,
        )
    if data[("TargetResponseTime", "Average")] is not None:
        row["latency_ms"] = int(
            round((data[("TargetResponseTime", "Average")]) * 1000, 0)
        )
    return row


def get_classic_load_balancer_metrics(cloudwatch, lb_name, start, now):
    elb_metrics = {
        "Latency": "Average",
        "RequestCount": "Sum",
        "HTTPCode_Backend_5XX": "Sum",
        "HTTPCode_Backend_4XX": "Sum",
    }
    row = {}
    data = {}
    for k, v in elb_metrics.items():
        res = cloudwatch.get_metric_statistics(
            Namespace="AWS/ELB",
            MetricName=k,
            Dimensions=[{"Name": "LoadBalancerName", "Value": lb_name}],
            StartTime=start,
            EndTime=now,
            Period=60,
            Statistics=[v],
        )
        most_recent = sorted(res["Datapoints"], key=lambda x: x["Timestamp"])[-1:]
        if most_recent:
            data[(k, v)] = most_recent[0][v]
        else:
            data[(k, v)] = None
    if data[("RequestCount", "Sum")] is not None:
        requests_per_min = data[("RequestCount", "Sum")]
        row["requests_per_sec"] = round(requests_per_min / 60, 2)
    else:
        requests_per_min = 0
    if data[("HTTPCode_Backend_4XX", "Sum")] is not None:
        row["4xx_percentage"] = round(
            (data[("HTTPCode_Backend_4XX", "Sum")]) / (requests_per_min + 0.0001), 2
        )
    if data[("HTTPCode_Backend_5XX", "Sum")] is not None:
        row["5xx_percentage"] = round(
            (data[("HTTPCode_Backend_5XX", "Sum")]) / (requests_per_min + 0.0001), 2
        )
    if data[("Latency", "Average")] is not None:
        row["latency_ms"] = int(round((data[("Latency", "Average")]) * 1000, 0))
    return row


@cli.command()
@region_option
@output_option
@field_option
@watch_option
@watchrefresh_option
@click.option("--all", is_flag=True, help="Show all stacks, including deleted ones")
@click.argument("stack_ref", nargs=-1)
@stacktrace_visible_option
def health(region, stack_ref, all, output, field, w, watch):
    """Show stack health (ELB req/s, ..)"""

    check_credentials(region)

    cloudwatch = BotoClientProxy("cloudwatch", region)

    stack_refs = get_stack_refs(stack_ref)

    for _ in watching(w, watch):
        rows = []
        start = datetime.datetime.utcnow() - datetime.timedelta(minutes=5)
        now = datetime.datetime.utcnow()
        paginator = cloudwatch.get_paginator("list_metrics")
        alb_ids = {}
        for page in paginator.paginate(
            Namespace="AWS/ApplicationELB",
            MetricName="RequestCount",
            Dimensions=[{"Name": "LoadBalancer"}],
        ):
            for metric in page["Metrics"]:
                alb_id = "".join(
                    [
                        d["Value"]
                        for d in metric["Dimensions"]
                        if d["Name"] == "LoadBalancer"
                    ]
                )
                alb_ids[alb_id.split("/")[1]] = alb_id
        for stack in get_stacks(stack_refs, region, all=all):
            lb_name = get_load_balancer_name(
                stack_name=stack.name, stack_version=stack.version
            )
            instance_health = get_instance_health(lb_name, region)
            row = {
                "stack_name": stack.name,
                "version": stack.version,
                "status": stack.StackStatus,
                "healthy_hosts": get_healthy_instances(instance_health),
                "creation_time": calendar.timegm(stack.CreationTime.timetuple()),
            }
            alb_id = alb_ids.get(lb_name)
            if alb_id:
                row.update(
                    get_application_load_balancer_metrics(
                        cloudwatch, alb_id, start, now
                    )
                )
            else:
                row.update(
                    get_classic_load_balancer_metrics(cloudwatch, lb_name, start, now)
                )
            rows.append(row)

        rows.sort(key=lambda x: (x["stack_name"], x["version"]))

        with OutputFormat(output):
            columns = filter_output_columns(
                [
                    "stack_name",
                    "version",
                    "status",
                    "healthy_hosts",
                    "requests_per_sec",
                    "4xx_percentage",
                    "5xx_percentage",
                    "latency_ms",
                ],
                field,
            )
            print_table(columns, rows, styles=STYLES, titles=TITLES)


@cli.command()
@click.argument("definition", type=DEFINITION)
@click.argument("version", callback=validate_version)
@click.argument("parameter", nargs=-1)
@region_option
@parameter_file_option
@click.option(
    "--disable-rollback",
    is_flag=True,
    help="Disable Cloud Formation rollback on failure",
)
@click.option("--dry-run", is_flag=True, help="No-op mode: show what would be created")
@click.option("-f", "--force", is_flag=True, help="Ignore failing validation checks")
@click.option("--update-if-exists", is_flag=True, help="Updates the stack if it exists")
@click.option("-t", "--tag", help="Tags to associate with the stack.", multiple=True)
@stacktrace_visible_option
def create(
    definition,
    region,
    version,
    parameter,
    disable_rollback,
    dry_run,
    force,
    tag,
    parameter_file,
    update_if_exists,
):
    """Create a new Cloud Formation stack from the given Senza definition file"""

    data = create_cf_template(
        definition, region, version, parameter, force, parameter_file
    )

    for tag_kv in tag:
        try:
            key, value = tag_kv.split("=")
        except ValueError:
            fatal_error(
                "Invalid tag {}. Tags should be in the form of key=value".format(tag_kv)
            )
        data["Tags"].append({"Key": key, "Value": value})

    cf = BotoClientProxy("cloudformation", region)

    update_stack = False

    with Action("Creating Cloud Formation stack {}..".format(data["StackName"])) as act:
        try:
            if dry_run:
                info("**DRY-RUN** {}".format(data["NotificationARNs"]))
                info(" Tags: {}".format(data["Tags"]))
            else:
                cf.create_stack(DisableRollback=disable_rollback, **data)
        except ClientError as e:
            if extract_client_error_code(e) == "AlreadyExistsException":
                if not update_if_exists:
                    act.fatal_error(
                        "Stack {StackName} already exists. "
                        "Please choose another version.".format_map(data)
                    )
                else:
                    act.warning(
                        "Stack {StackName} already exists. "
                        "It will be updated".format_map(data)
                    )
                    update_stack = True
            else:
                raise

    if update_stack:
        update_stack_from_template(region, data, dry_run)


@cli.command()
@click.argument("definition", type=DEFINITION)
@click.argument("version", callback=validate_version)
@click.argument("parameter", nargs=-1)
@region_option
@parameter_file_option
@click.option(
    "--disable-rollback",
    is_flag=True,
    help="Disable Cloud Formation rollback on failure",
)
@click.option("--dry-run", is_flag=True, help="No-op mode: show what would be created")
@click.option("-f", "--force", is_flag=True, help="Ignore failing validation checks")
@stacktrace_visible_option
def update(
    definition,
    region,
    version,
    parameter,
    disable_rollback,
    dry_run,
    force,
    parameter_file,
):
    """Update an existing Cloud Formation stack from the given Senza
    definition file"""

    data = create_cf_template(
        definition, region, version, parameter, force, parameter_file
    )
    update_stack_from_template(region, data, dry_run)


@cli.command("print")
@click.argument("definition", type=DEFINITION)
@click.argument("version", callback=validate_version)
@click.argument("parameter", nargs=-1)
@region_option
@parameter_file_option
@json_output_option
@click.option("-f", "--force", is_flag=True, help="Ignore failing validation checks")
@stacktrace_visible_option
def print_cfjson(definition, region, version, parameter, output, force, parameter_file):
    """Print the generated Cloud Formation template"""

    data = create_cf_template(
        definition, region, version, parameter, force, parameter_file, pretty=True
    )
    print_json(data["TemplateBody"], output)


def create_cf_template(
    definition, region, version, parameter, force, parameter_file, pretty=False
):
    region = get_region(region)
    if parameter_file:
        parameter_from_file = read_parameter_file(parameter_file)
        parameter = parameter + parameter_from_file
    check_credentials(region)
    account_info = AccountArguments(region=region)
    args = parse_args(definition, region, version, parameter, account_info)

    with Action("Generating Cloud Formation template..") as action:
        try:
            data = evaluate(definition.copy(), args, account_info, force)
        except VPCError as e:
            action.fatal_error("Fatal Error: {}".format(e))
    stack_name = "{0}-{1}".format(
        data["Mappings"]["Senza"]["Info"]["StackName"],
        data["Mappings"]["Senza"]["Info"]["StackVersion"],
    )
    if len(stack_name) > 128:
        fatal_error(
            'Error: Stack name "{}" cannot exceed 128 characters. '.format(stack_name)
            + "Please choose another name/version."
        )

    parameters = []
    for name, parameter in data.get("Parameters", {}).items():
        parameters.append(
            {"ParameterKey": name, "ParameterValue": getattr(args, name, None)}
        )

    tags = {}
    senza_tags = data["Mappings"]["Senza"]["Info"].get("Tags")
    if isinstance(senza_tags, dict):
        tags.update(senza_tags)
    elif isinstance(senza_tags, list):
        for tag in senza_tags:
            for key, value in tag.items():
                # # As the SenzaInfo is not evaluated, we explicitly evaluate the values here
                tags[key] = evaluate_template(value, info, [], args, account_info)

    tags.update(
        {
            "Name": stack_name,
            "StackName": data["Mappings"]["Senza"]["Info"]["StackName"],
            "StackVersion": data["Mappings"]["Senza"]["Info"]["StackVersion"],
        }
    )
    tags_list = []
    tags_mapping_list = []
    for k, v in tags.items():
        tags_list.append({"Key": k, "Value": v})
        tags_mapping_list.append({k: v})
    data["Mappings"]["Senza"]["Info"]["Tags"] = tags_mapping_list

    if "OperatorTopicId" in data["Mappings"]["Senza"]["Info"]:
        topic = data["Mappings"]["Senza"]["Info"]["OperatorTopicId"]
        topic_arn = resolve_topic_arn(region, topic)
        if not topic_arn:
            fatal_error('Error: SNS topic "{}" does not exist'.format(topic))
        topics = [topic_arn]
    else:
        topics = []

    capabilities = get_required_capabilities(data)
    if pretty:
        cfjson = json.dumps(data, sort_keys=True, indent=4)
    else:
        cfjson = json.dumps(data, separators=(",", ":"))
    return {
        "StackName": stack_name,
        "TemplateBody": cfjson,
        "Parameters": parameters,
        "Tags": tags_list,
        "NotificationARNs": topics,
        "Capabilities": capabilities,
    }


@cli.command()
@click.argument("stack_ref", nargs=-1)
@region_option
@click.option("--dry-run", is_flag=True, help="No-op mode: show what would be deleted")
@click.option(
    "-g",
    "--ignore-non-existent",
    is_flag=True,
    help="Do not show error when stack does not exist",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Allow deleting multiple stacks and stacks with traffic",
)
@click.option("-i", "--interactive", is_flag=True, help="Prompt before every deletion")
@stacktrace_visible_option
def delete(stack_ref, region, dry_run, force, interactive, ignore_non_existent):
    """Delete a single Cloud Formation stack"""

    stack_refs = get_stack_refs(stack_ref)
    check_credentials(region)

    if not stack_refs:
        raise click.UsageError("Please specify at least one stack")

    cf = CloudFormation(region=region)
    stacks = [stack for stack in cf.get_stacks() if matches_any(stack.name, stack_refs)]

    if (
        not all_with_version(stack_refs)
        and len(stacks) > 1
        and not dry_run
        and not force
    ):
        fatal_error(
            "Error: {} matching stacks found. ".format(len(stacks))
            + 'Please use the "--force" flag if you really want to '
            "delete multiple stacks."
        )

    if not stacks and not ignore_non_existent:
        fatal_error("Error: Stack {} not found!".format(stack_refs[0].name))

    for stack in stacks:

        for r in stack.resources:
            if isinstance(r, Route53Record):
                has_traffic = r.weight is not None and r.weight
                if has_traffic and not force:
                    fatal_error(
                        "Error: Stack {} has traffic!\n"
                        "Use --force if you really want "
                        "to delete it".format(stack.name)
                    )

        if interactive and not click.confirm("Delete '{}'?".format(stack.name)):
            continue

        with Action("Deleting Cloud Formation stack {}..".format(stack.name)):
            if not dry_run:
                stack.delete()


def format_resource_type(resource_type):
    if resource_type and resource_type.startswith("AWS::"):
        return resource_type[5:]
    return resource_type


@cli.command()
@click.argument("stack_ref", nargs=-1)
@region_option
@watch_option
@watchrefresh_option
@output_option
@field_option
@stacktrace_visible_option
def resources(stack_ref, region, w, watch, output, field):
    """Show all resources of a single Cloud Formation stack"""

    stack_refs = get_stack_refs(stack_ref)
    check_credentials(region)
    cf = BotoClientProxy("cloudformation", region)

    for _ in watching(w, watch):
        rows = []
        for stack in get_stacks(stack_refs, region):
            resources = cf.describe_stack_resources(StackName=stack.StackName)[
                "StackResources"
            ]

            for resource in resources:
                d = resource.copy()
                d["stack_name"] = stack.name
                d["version"] = stack.version
                d["resource_type"] = format_resource_type(d["ResourceType"])
                d["creation_time"] = calendar.timegm(resource["Timestamp"].timetuple())
                rows.append(d)

        rows.sort(key=lambda x: (x["stack_name"], x["version"], x["LogicalResourceId"]))

        with OutputFormat(output):
            columns = filter_output_columns(
                [
                    "stack_name",
                    "version",
                    "LogicalResourceId",
                    "resource_type",
                    "ResourceStatus",
                    "creation_time",
                ],
                field,
            )
            print_table(columns, rows, styles=STYLES, titles=TITLES)


@cli.command()
@click.argument("stack_ref", nargs=-1)
@region_option
@watch_option
@watchrefresh_option
@output_option
@field_option
@stacktrace_visible_option
def events(stack_ref, region, w, watch, output, field):
    """Show all Cloud Formation events for a single stack"""

    stack_refs = get_stack_refs(stack_ref)
    check_credentials(region)
    cf = BotoClientProxy("cloudformation", region)

    for _ in watching(w, watch):
        rows = []
        for stack in get_stacks(stack_refs, region):
            events = cf.describe_stack_events(StackName=stack.StackId)["StackEvents"]

            for event in events:
                d = event.copy()
                d["stack_name"] = stack.name
                d["version"] = stack.version
                d["resource_type"] = format_resource_type(d["ResourceType"])
                d["event_time"] = calendar.timegm(event["Timestamp"].timetuple())
                rows.append(d)

        rows.sort(key=lambda x: x["event_time"])

        with OutputFormat(output):
            columns = filter_output_columns(
                [
                    "stack_name",
                    "version",
                    "resource_type",
                    "LogicalResourceId",
                    "ResourceStatus",
                    "ResourceStatusReason",
                    "event_time",
                ],
                field,
            )
            print_table(
                columns,
                rows,
                styles=STYLES,
                titles=TITLES,
                max_column_widths=MAX_COLUMN_WIDTHS,
            )


@cli.command()
@click.argument("definition_file", type=click.File("w"))
@region_option
@click.option("-t", "--template", help="Use a custom template", metavar="TEMPLATE_ID")
@click.option(
    "-v",
    "--user-variable",
    help="Provide user variables for the template",
    metavar="KEY=VAL",
    multiple=True,
    type=KEY_VAL,
)
@stacktrace_visible_option
def init(definition_file, region, template, user_variable):
    """Initialize a new Senza definition"""

    check_credentials(region)
    account_info = AccountArguments(region=region)

    templates = get_templates()

    module = templates.get(template, None)

    if not module:
        module = choice(
            "Please select the project template",
            [
                (module, get_template_description(name, module))
                for name, module in sorted(templates.items(), key=lambda x: x[0])
            ],  # sort by key
            default="webapp",
        )

    variables = {}
    for key_val in user_variable:
        key, val = key_val
        variables[key] = val
    variables = module.gather_user_variables(variables, region, account_info)
    with Action("Generating Senza definition file {}..".format(definition_file.name)):
        definition = module.generate_definition(variables)
        definition_file.write(definition)


def get_instance_health(stack_name: str, region: str) -> dict:
    if stack_name is None:
        return {}
    instance_health = {}
    elb = BotoClientProxy("elb", region)
    try:
        instance_states = elb.describe_instance_health(LoadBalancerName=stack_name)[
            "InstanceStates"
        ]
        for istate in instance_states:
            instance_health[istate["InstanceId"]] = camel_case_to_underscore(
                istate["State"]
            ).upper()
    except ClientError as e:
        # retry with ELBv2
        error_code = extract_client_error_code(e)
        if error_code == "LoadBalancerNotFound":
            elbv2 = BotoClientProxy("elbv2", region)
            try:
                response = elbv2.describe_target_groups(Names=[stack_name])
                for tg in response["TargetGroups"]:
                    response = elbv2.describe_target_health(
                        TargetGroupArn=tg["TargetGroupArn"]
                    )
                    for target_health in response["TargetHealthDescriptions"]:
                        instance_health[
                            target_health["Target"]["Id"]
                        ] = camel_case_to_underscore(
                            target_health["TargetHealth"]["State"]
                        ).upper()
            except ClientError as e:
                inner_error_code = extract_client_error_code(e)
                if inner_error_code not in (
                    "TargetGroupNotFound",
                    "ValidationError",
                    "Throttling",
                ):
                    raise
        # ignore ValidationError "LoadBalancer name cannot be longer than 32 characters"
        # ignore rate limit exceeded errors
        elif error_code not in ("ValidationError", "Throttling"):
            raise
    return instance_health


def get_healthy_instances(instance_health: dict) -> int:
    if not instance_health:
        # if we have no instances at all -> treat as "unknown"
        return None
    return len([i for i in instance_health.values() if i in ("IN_SERVICE", "HEALTHY")])


def get_instance_user_data(instance) -> dict:
    try:
        attrs = instance.describe_attribute(Attribute="userData")
        data_b64 = attrs["UserData"]["Value"]
        data_yaml = base64.b64decode(data_b64)
        data_dict = yaml.safe_load(data_yaml)
        return data_dict
    except Exception as e:
        # there's just too many ways this can fail, catch 'em all
        sys.stderr.write("Failed to query instance user data: {}\n".format(e))
    return {}


def get_instance_docker_image_source(instance) -> str:
    return get_instance_user_data(instance).get("source", "")


@cli.command()
@click.argument("stack_ref", nargs=-1)
@click.option(
    "--all",
    is_flag=True,
    help="Show all instances, including instances not part of any stack",
)
@click.option("--terminated", is_flag=True, help="Show instances in TERMINATED state")
@click.option(
    "-d",
    "--docker-image",
    is_flag=True,
    help="Show docker image source for every instance listed",
)
@click.option(
    "-p", "--piu", metavar="REASON", help="execute PIU request-access command"
)
@click.option(
    "-O",
    "--odd-host",
    help="Odd SSH bastion hostname",
    envvar="ODD_HOST",
    metavar="HOSTNAME",
)
@region_option
@output_option
@field_option
@watch_option
@watchrefresh_option
@stacktrace_visible_option
def instances(
    stack_ref,
    all,
    terminated,
    docker_image,
    piu,
    odd_host,
    region,
    output,
    field,
    w,
    watch,
):
    """List the stack's EC2 instances"""

    stack_refs = get_stack_refs(stack_ref)
    check_credentials(region)

    ec2 = boto3.resource("ec2", region)

    if all:
        filters = []
    else:
        # filter out instances without a Name tag
        filters = [{"Name": "tag-key", "Values": ["Name"]}]

    # Semantically equivalent to the less efficient client side filtering on != TERMINATED
    if not terminated:
        filters.append(
            {"Name": "instance-state-name", "Values": ["pending", "running", "shutting-down", "stopping", "stopped"]})

    opt_docker_column = " docker_source" if docker_image else ""

    for _ in watching(w, watch):
        rows = []

        for instance in ec2.instances.filter(Filters=filters):
            cf_stack_name = get_tag(instance.tags, "Name")
            stack_name = get_tag(instance.tags, "StackName")
            stack_version = get_tag(instance.tags, "StackVersion")
            if not stack_refs or matches_any(cf_stack_name, stack_refs):
                instance_health = get_instance_health(cf_stack_name, region)

                docker_source = (
                    get_instance_docker_image_source(instance)
                    if docker_image
                    else ""
                )

                rows.append(
                    {
                        "stack_name": stack_name or "",
                        "version": stack_version or "",
                        "resource_id": get_tag(
                            instance.tags, "aws:cloudformation:logical-id"
                        ),
                        "instance_id": instance.id,
                        "public_ip": instance.public_ip_address,
                        "private_ip": instance.private_ip_address,
                        "state": instance.state["Name"].upper().replace("-", "_"),
                        "lb_status": instance_health.get(instance.id),
                        "docker_source": docker_source,
                        "launch_time": instance.launch_time.timestamp()
                    }
                )

        rows.sort(key=lambda r: (r["stack_name"], r["version"], r["instance_id"]))

        with OutputFormat(output):
            columns = filter_output_columns(
                [
                    "stack_name",
                    "version",
                    "resource_id",
                    "instance_id",
                    "public_ip",
                    "private_ip",
                    "state",
                    "lb_status{}".format(opt_docker_column),
                    "launch_time",
                ],
                field,
            )
            print_table(columns, rows, styles=STYLES, titles=TITLES)

        if piu is not None:
            odd_host = odd_host or Piu.find_odd_host(region)
            auto_connect = len(rows) == 1
            for row in rows:
                if row["private_ip"] is not None:
                    Piu.request_access(
                        instance=row["private_ip"],
                        reason=piu,
                        odd_host=odd_host,
                        connect=auto_connect,
                    )


@cli.command()
@click.argument("stack_ref", nargs=-1)
@region_option
@output_option
@field_option
@watch_option
@watchrefresh_option
@stacktrace_visible_option
def status(stack_ref, region, output, field, w, watch):
    """Show stack status information"""

    stack_refs = get_stack_refs(stack_ref)
    check_credentials(region)

    ec2 = boto3.resource("ec2", region)
    cf = boto3.resource("cloudformation", region)

    for _ in watching(w, watch):
        rows = []
        for stack in sorted(get_stacks(stack_refs, region)):
            instance_health = get_instance_health(stack.StackName, region)

            main_dns_resolves = None
            version_addresses = set()
            main_addresses = set()
            http_status = None
            for res in cf.Stack(stack.StackId).resource_summaries.all():
                if res.resource_type == "AWS::Route53::RecordSet":
                    name = res.physical_resource_id
                    if not name:
                        # physical resource ID will be empty during stack creation
                        continue
                    if "version" in res.logical_id.lower():
                        # VersionDomain -> check HTTPS reachability
                        # (won't work for internal ELBs, but we don't care here)
                        try:
                            requests.get("https://{}/".format(name), timeout=1)
                            http_status = "OK"
                        except Exception:
                            http_status = "ERROR"
                        version_addresses = resolve_to_ip_addresses(name)
                    else:
                        # MainDomain -> check whether DNS resolves to this stack version
                        main_addresses = resolve_to_ip_addresses(name)

            if version_addresses and main_addresses:
                main_dns_resolves = bool(version_addresses & main_addresses)

            instances = list(
                ec2.instances.filter(
                    Filters=[
                        {
                            "Name": "tag:Name",
                            "Values": [stack.StackName],
                        }
                    ]
                )
            )
            rows.append(
                {
                    "stack_name": stack.name,
                    "version": stack.version,
                    "status": stack.StackStatus,
                    "total_instances": len(instances),
                    "running_instances": len(
                        [i for i in instances if i.state["Name"] == "running"]
                    ),
                    "healthy_instances": get_healthy_instances(instance_health),
                    "lb_status": ",".join(set(instance_health.values())),
                    "main_dns": main_dns_resolves,
                    "http_status": http_status,
                }
            )

        with OutputFormat(output):
            columns = filter_output_columns(
                [
                    "stack_name",
                    "version",
                    "status",
                    "total_instances",
                    "running_instances",
                    "healthy_instances",
                    "lb_status",
                    "http_status",
                    "main_dns",
                ],
                field,
            )
            print_table(columns, rows, styles=STYLES, titles=TITLES)


@cli.command()
@click.argument("stack_ref", nargs=-1)
@region_option
@output_option
@field_option
@watch_option
@watchrefresh_option
@stacktrace_visible_option
def domains(stack_ref, region, output, field, w, watch):
    """List the stack's Route53 domains"""

    stack_refs = get_stack_refs(stack_ref)
    check_credentials(region)

    cf = boto3.resource("cloudformation", region)

    records_by_name = {}

    for _ in watching(w, watch):
        rows = []
        for stack in get_stacks(stack_refs, region):
            if stack.StackStatus == "ROLLBACK_COMPLETE":
                # performance optimization: do not call EC2 API for "dead" stacks
                continue

            for res in cf.Stack(stack.StackId).resource_summaries.all():
                if res.resource_type == "AWS::Route53::RecordSet":
                    name = res.physical_resource_id
                    if name not in records_by_name:
                        hosted_zone = next(Route53.get_hosted_zones(name))
                        zone_name = hosted_zone.domain_name
                        for rec in get_records(zone_name):
                            record = Route53Record.from_boto_dict(rec)
                            records_by_name[
                                (rec["Name"].rstrip("."), rec.get("SetIdentifier"))
                            ] = record
                    record = records_by_name.get(
                        (name, stack.StackName)
                    ) or records_by_name.get(
                        (name, None)
                    )  # type: Route53Record
                    row = {
                        "stack_name": stack.name,
                        "version": stack.version,
                        "resource_id": res.logical_id,
                        "domain": res.physical_resource_id,
                        "weight": None,
                        "type": None,
                        "value": None,
                        "create_time": calendar.timegm(
                            res.last_updated_timestamp.timetuple()
                        ),
                    }
                    if record:
                        if record.resource_records:
                            value = ",".join(
                                [r["Value"] for r in record.resource_records]
                            )
                        elif record.alias_target:
                            value = record.alias_target["DNSName"]
                        else:
                            value = ""
                        row.update(
                            {
                                "weight": (
                                    str(record.weight)
                                    if record.weight is not None
                                    else ""
                                ),
                                "type": record.type.value,
                                "value": value,
                            }
                        )
                    rows.append(row)

        with OutputFormat(output):
            columns = filter_output_columns(
                [
                    "stack_name",
                    "version",
                    "resource_id",
                    "domain",
                    "weight",
                    "type",
                    "value",
                    "create_time",
                ],
                field,
            )
            print_table(columns, rows, styles=STYLES, titles=TITLES)


@cli.command()
@click.argument("stack_name")
@click.argument("stack_version", required=False)
@click.argument("percentage", type=FloatRange(0, 100, clamp=True), required=False)
@click.option(
    "-t",
    "--timeout",
    default=None,
    type=click.IntRange(1, 600, clamp=True),
    help=(
        "Timeout for waiting for stacks to be ready to perform the "
        "traffic change (by default it does not wait)"
    ),
)
@click.option(
    "-i",
    "--interval",
    default=5,
    type=click.IntRange(1, 600, clamp=True),
    help="Time between checks (default: 5s)",
)
@region_option
@output_option
@stacktrace_visible_option
def traffic(stack_name, stack_version, percentage, region, output, timeout, interval):
    """Route traffic to a specific stack (weighted DNS record)"""

    stack_refs = get_stack_refs([stack_name, stack_version])
    check_credentials(region)

    with OutputFormat(output):
        for ref in stack_refs:  # it's expected to always iterate only once
            if percentage is None:
                print_version_traffic(ref, region)
            else:
                related_stacks_refs = get_stack_refs([stack_name])
                with all_stacks_in_final_state(
                    related_stacks_refs, region, timeout=timeout, interval=interval
                ):
                    change_version_traffic(ref, percentage, region)


@cli.command()
@click.argument("stack_ref", nargs=-1)
@click.option(
    "--hide-older-than",
    help="Hide images older than X days (default: 21)",
    type=int,
    default=21,
    metavar="DAYS",
)
@click.option("--show-instances", is_flag=True, help="Show EC2 instance IDs")
@region_option
@output_option
@field_option
@stacktrace_visible_option
def images(stack_ref, region, output, field, hide_older_than, show_instances):
    """Show all used AMIs and available Taupage AMIs"""

    stack_refs = get_stack_refs(stack_ref)
    check_credentials(region)

    ec2 = boto3.resource("ec2", region)

    instances_by_image = collections.defaultdict(list)
    for inst in ec2.instances.all():
        if inst.state["Name"] == "terminated":
            # do not count TERMINATED EC2 instances
            continue
        stack_name = get_tag(inst.tags, "aws:cloudformation:stack-name")
        if not stack_refs or matches_any(stack_name, stack_refs):
            instances_by_image[inst.image_id].append(inst)

    images = {}
    for image in ec2.images.filter(ImageIds=list(instances_by_image.keys())):
        images[image.id] = image
    if not stack_refs:
        for channel in taupage.CHANNELS.values():
            filters = [
                {"Name": "name", "Values": [channel.ami_wildcard]},
                {"Name": "state", "Values": ["available"]},
            ]
            for image in ec2.images.filter(Filters=filters):
                images[image.id] = image
    rows = []
    cutoff = datetime.datetime.now() - datetime.timedelta(days=hide_older_than)
    for image in images.values():
        row = image.meta.data.copy()
        creation_time = parse_time(image.creation_date)
        row["creation_time"] = creation_time
        row["instances"] = ", ".join(sorted(i.id for i in instances_by_image[image.id]))
        row["total_instances"] = len(instances_by_image[image.id])
        stacks = set()
        for instance in instances_by_image[image.id]:
            stack_name = get_tag(instance.tags, "aws:cloudformation:stack-name")
            # EC2 instance might not be part of a CF stack
            if stack_name:
                stacks.add(stack_name)
        row["stacks"] = ", ".join(sorted(stacks))

        if creation_time is None:
            continue

        if creation_time > cutoff.timestamp() or row["total_instances"]:
            rows.append(row)

    rows.sort(key=lambda x: x.get("Name"))
    with OutputFormat(output):
        instances_column_name = "instances" if show_instances else "total_instances"

        columns = filter_output_columns(
            [
                "ImageId",
                "Name",
                "OwnerId",
                "Description",
                "stacks",
                instances_column_name,
                "creation_time",
            ],
            field,
        )
        print_table(columns, rows, titles=TITLES, max_column_widths=MAX_COLUMN_WIDTHS)


def is_ip_address(x: str):
    """
    Checks if x is a valid ip address.
    """
    try:
        ipaddress.ip_address(x)
        return True
    except ValueError:
        return False


def get_console_line_style(line: str):
    if "ERROR:" in line:
        return {"fg": "red", "bold": True}
    elif "WARNING:" in line:
        return {"fg": "yellow", "bold": True}
    elif "SUCCESS:" in line:
        return {"fg": "green", "bold": True}
    elif "INFO:" in line:
        return {"bold": True}
    else:
        return {}


def print_console(line: str):
    style = get_console_line_style(line)
    click.secho(line, **style)


@cli.command()
@click.argument("instance_or_stack_ref", nargs=-1)
@click.option(
    "-l",
    "--limit",
    help="Show last N lines of console output (default: 25)",
    type=int,
    default=25,
    metavar="N",
)
@region_option
@watch_option
@watchrefresh_option
@stacktrace_visible_option
def console(instance_or_stack_ref, limit, region, w, watch):
    """Print EC2 instance console output.

    INSTANCE_OR_STACK_REF can be an instance ID, private IP address or stack name/version.

    Ex:\n
    senza console my-stack-template.yml version1\n
    senza console my-stack-template.yml\n
    senza console my-stack-name version1\n
    senza console my-stack-name\n
    senza console 172.23.22.240\n
    senza console i-7c3a3de5\n
    senza console
    """

    if instance_or_stack_ref and all(x.startswith("i-") for x in instance_or_stack_ref):
        stack_refs = None
        filters = [{"Name": "instance-id", "Values": list(instance_or_stack_ref)}]
    elif instance_or_stack_ref and all(is_ip_address(x) for x in instance_or_stack_ref):
        stack_refs = None
        filters = [
            {"Name": "private-ip-address", "Values": list(instance_or_stack_ref)}
        ]
    else:
        stack_refs = get_stack_refs(instance_or_stack_ref)
        # filter out instances not part of any stack
        filters = [{"Name": "tag-key", "Values": ["aws:cloudformation:stack-name"]}]

    check_credentials(region)

    ec2 = boto3.resource("ec2", region)

    for _ in watching(w, watch):

        found_match = False
        for instance in ec2.instances.filter(Filters=filters):

            cf_stack_name = get_tag(instance.tags, "aws:cloudformation:stack-name")
            if not stack_refs or matches_any(cf_stack_name, stack_refs):
                found_match = True
                output = {}
                try:
                    output = instance.console_output()
                except Exception:
                    pass
                click.secho(
                    "Showing last {} lines of {}/{}..".format(
                        limit, cf_stack_name, instance.private_ip_address or instance.id
                    ),
                    bold=True,
                )
                if isinstance(output, dict) and output.get("Output"):
                    for line in output["Output"].split("\n")[-limit:]:
                        print_console(line)
        if not found_match:
            if stack_refs is None:
                fatal_error(
                    "No EC2 instance with id '{}'.".format(instance_or_stack_ref[0])
                )
            elif instance_or_stack_ref:
                fatal_error(
                    "No stack matching '{}'{}.".format(
                        stack_refs[0].name,
                        " with version '{}'".format(stack_refs[0].version)
                        if stack_refs[0].version is not None
                        else "",
                    )
                )
            else:
                fatal_error("No EC2 instances in region '{}'.".format(region))


@cli.command()
@click.argument("stack_ref", nargs=-1)
@region_option
@json_output_option
@stacktrace_visible_option
def dump(stack_ref, region, output):
    """Dump Cloud Formation template of existing stack"""

    stack_refs = get_stack_refs(stack_ref)
    check_credentials(region)

    cf = BotoClientProxy("cloudformation", region)

    for stack in get_stacks(stack_refs, region):
        data = cf.get_template(StackName=stack.StackName)["TemplateBody"]
        cfjson = json.dumps(data, sort_keys=True, indent=4)
        print_json(cfjson, output)


def get_auto_scaling_groups_and_elasti_groups(stacks, region):
    """
    Returns data for both AWS Auto Scaling Groups and ElastiGroups

    Note: This method will eventually replace get_auto_scaling_groups when the remaining commands support ElastiGroups
    """
    cf = BotoClientProxy("cloudformation", region)
    for stack in stacks:
        resources = cf.describe_stack_resources(StackName=stack.StackName)[
            "StackResources"
        ]

        for resource in resources:
            if resource["ResourceType"] in VALID_AUTO_SCALING_GROUPS:
                yield {
                    "type": resource["ResourceType"],
                    "resource_id": resource["PhysicalResourceId"],
                    "stack_name": resource["StackName"],
                }


def get_auto_scaling_groups(stack_refs, region):
    cf = BotoClientProxy("cloudformation", region)
    for stack in get_stacks(stack_refs, region):
        resources = cf.describe_stack_resources(StackName=stack.StackName)[
            "StackResources"
        ]

        for resource in resources:
            if resource["ResourceType"] == "AWS::AutoScaling::AutoScalingGroup":
                asg_name = resource["PhysicalResourceId"]
                yield asg_name


@cli.command()
@click.argument("stack_ref", nargs=-1)
@region_option
@click.option(
    "--image",
    metavar="AMI_ID_OR_LATEST",
    help='Use specified image (AMI ID or one of "latest", "staging", "dev")',
)
@click.option(
    "--instance-type", metavar="INSTANCE_TYPE", help="Use specified EC2 instance type"
)
@click.option("--user-data", metavar="YAML", help="Patch properties in user data YAML")
@stacktrace_visible_option
def patch(stack_ref, region, image, instance_type, user_data):
    """Patch specific properties of existing stack.

    Currently supports patching ASG launch configurations and ElastiGroup groups."""

    stack_refs = get_stack_refs(stack_ref)
    check_credentials(region)

    if image in taupage.CHANNELS:
        ami = taupage.find_image(region, channel=taupage.CHANNELS[image])
        if ami is None:
            fatal_error("No Taupage AMI found for {}".format(image))
        image = ami.id

    properties = {
        "ImageId": image,
        "InstanceType": instance_type,
        "UserData": yaml.safe_load(user_data) if user_data else None,
    }
    # remove empty values
    properties = {k: v for k, v in properties.items() if v}

    if not properties:
        raise click.UsageError(
            'Nothing to patch. Please specify at least one patch option (e.g. "--image").'
        )

    asg = BotoClientProxy("autoscaling", region)

    stacks = get_stacks(stack_refs, region)
    for group in get_auto_scaling_groups_and_elasti_groups(stacks, region):
        if group["type"] == ELASTIGROUP_RESOURCE_TYPE:
            patch_spotinst_elastigroup(
                properties, group["resource_id"], region, group["stack_name"]
            )
        elif group["type"] == AUTO_SCALING_GROUP_TYPE:
            patch_aws_asg(properties, region, asg, group["resource_id"])


def patch_aws_asg(properties, region, asg, asg_name):
    """
    Patch an AWS Auto Scaling Group
    """
    with Action("Patching Auto Scaling Group {}..".format(asg_name)) as act:
        result = asg.describe_auto_scaling_groups(AutoScalingGroupNames=[asg_name])
        groups = result["AutoScalingGroups"]
        for group in groups:
            if not patch_auto_scaling_group(group, region, properties):
                act.ok("NO CHANGES")


def patch_spotinst_elastigroup(properties, elastigroup_id, region, stack_name):
    """
    Patch specific properties of an existing ElastiGroup
    """

    spotinst_account_data = elastigroup_api.get_spotinst_account_data(
        region, stack_name
    )

    with Action(
        "Patching ElastiGroup {} (ID: {})..".format(stack_name, elastigroup_id)
    ) as act:
        groups = elastigroup_api.get_elastigroup(elastigroup_id, spotinst_account_data)

        for group in groups:
            if not patch_elastigroup(
                group, properties, elastigroup_id, spotinst_account_data
            ):
                act.ok("NO CHANGES")


@cli.command("respawn-instances")
@click.argument("stack_ref", nargs=-1)
@click.option(
    "--inplace",
    is_flag=True,
    help="Perform inplace update, do not scale out. Ignored for ElastiGroups.",
)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    help="Force respawn even if Launch Configuration is unchanged. Ignored for ElastiGroups.",
)
@click.option(
    "--batch_size_percentage",
    metavar="PERCENTAGE",
    type=click.IntRange(0, 100, clamp=True),
    help="Percentage (int value) of the ElastiGroup cluster that is respawned in each step."
    " Valid only for stateless ElastiGroups. The default value for this of 20.",
)
@click.option(
    "--batch-per-subnet",
    is_flag=True,
    help="Recycle ElastiGroup instances in batches per subnet. Valid only for stateful ElastiGroups.",
)
@region_option
@stacktrace_visible_option
def respawn_instances(stack_ref, inplace, force, batch_size_percentage, batch_per_subnet, region):
    """Replace all EC2 instances in Auto Scaling Group(s)

    Performs a rolling update to prevent downtimes."""

    stack_refs = get_stack_refs(stack_ref)
    check_credentials(region)

    stacks = get_stacks(stack_refs, region)
    for group in get_auto_scaling_groups_and_elasti_groups(stacks, region):
        if group["type"] == AUTO_SCALING_GROUP_TYPE:
            respawn.respawn_auto_scaling_group(
                group["resource_id"], region, inplace=inplace, force=force
            )
        elif group["type"] == ELASTIGROUP_RESOURCE_TYPE:
            respawn.respawn_elastigroup(
                group["resource_id"], group["stack_name"], region, batch_size_percentage, batch_per_subnet
            )


@cli.command()
@click.argument("stack_ref", nargs=-1)
@click.argument("desired_capacity", type=click.IntRange(0, 100, clamp=True))
@click.option(
    "--min-size",
    metavar="MIN_SIZE",
    type=click.IntRange(0, 100, clamp=True),
    help="Define the MinSize to update the AutoScalingGroup.")
@click.option(
    "-f", "--force", is_flag=True, help="Force scaling multiple stacks if needed"
)
@region_option
@stacktrace_visible_option
def scale(stack_ref, region, desired_capacity, min_size, force):
    """Scale Auto Scaling Group to desired capacity"""

    stack_refs = get_stack_refs(stack_ref)
    check_credentials(region)

    stacks = get_stacks(stack_refs, region)
    stack_count = len(stacks)
    if not force and stack_count > 1:
        confirm_str = "Number of stacks to be scaled - {}. Do you want to continue?".format(
            stack_count
        )
        click.confirm(confirm_str, abort=True)

    asg = BotoClientProxy("autoscaling", region)
    for group in get_auto_scaling_groups_and_elasti_groups(stacks, region):
        if group["type"] == AUTO_SCALING_GROUP_TYPE:
            scale_auto_scaling_group(asg, group["resource_id"], desired_capacity, min_size)
        elif group["type"] == ELASTIGROUP_RESOURCE_TYPE:
            scale_elastigroup(
                group["resource_id"], group["stack_name"], desired_capacity, region
            )


def scale_elastigroup(elastigroup_id, stack_name, desired_capacity, region):
    """
    Commands to scale an ElastiGroup
    """
    spotinst_account_data = elastigroup_api.get_spotinst_account_data(
        region, stack_name
    )

    groups = elastigroup_api.get_elastigroup(elastigroup_id, spotinst_account_data)

    for group in groups:
        capacity = group["capacity"]

        with Action(
            "Scaling ElastiGroup {} (ID: {}) from {} to {} instances..".format(
                stack_name, elastigroup_id, capacity["target"], desired_capacity
            )
        ) as act:
            if capacity["target"] == desired_capacity:
                act.ok("NO CHANGES")
            else:
                minimum = (
                    desired_capacity
                    if capacity["minimum"] > desired_capacity
                    else capacity["minimum"]
                )
                maximum = (
                    desired_capacity
                    if capacity["maximum"] < desired_capacity
                    else capacity["maximum"]
                )

                elastigroup_api.update_capacity(
                    minimum,
                    maximum,
                    desired_capacity,
                    elastigroup_id,
                    spotinst_account_data,
                )


def scale_auto_scaling_group(asg, asg_name, desired_capacity, min_size):
    """
    Commands to scale an AWS Auto Scaling Group
    """
    group = respawn.get_auto_scaling_group(asg, asg_name)
    current_capacity = group["DesiredCapacity"]
    with Action(
        "Scaling {} from {} to {} instances..".format(
            asg_name, current_capacity, desired_capacity
        )
    ) as act:
        if current_capacity == desired_capacity:
            act.ok("NO CHANGES")
        else:
            kwargs = {}
            if min_size and desired_capacity < min_size:
                fatal_error(
                    "Desired capacity must be bigger than specified min_size value"
                )
            if not min_size and group["MinSize"] == 0:
                info(
                    "MinSize was set to 0 previously. This might result in "
                    "unexpected downscaling of the stack. Please use --min_size "
                    "to update the value."
                )
            if min_size:
                kwargs["MinSize"] = min_size
            if desired_capacity < group["MinSize"]:
                kwargs["MinSize"] = desired_capacity
            if desired_capacity > group["MaxSize"]:
                kwargs["MaxSize"] = desired_capacity
            asg.update_auto_scaling_group(
                AutoScalingGroupName=asg_name,
                DesiredCapacity=desired_capacity,
                **kwargs
            )


def failure_event(event: dict):
    status = event.get("ResourceStatus")
    return bool(
        event.get("ResourceStatusReason") and ("FAIL" in status or "ROLLBACK" in status)
    )


@cli.command()
@click.argument("stack_ref", nargs=-1)
@click.option(
    "-d",
    "--deletion",
    is_flag=True,
    help="Wait for deletion instead of CREATE_COMPLETE",
)
@click.option(
    "-t",
    "--timeout",
    type=click.IntRange(0, 7200, clamp=True),
    metavar="SECS",
    default=1800,
    help="Maximum wait time (default: 1800s)",
)
@click.option(
    "-i",
    "--interval",
    default=5,
    type=click.IntRange(1, 600, clamp=True),
    help="Time between checks (default: 5s)",
)
@region_option
@stacktrace_visible_option
def wait(stack_ref, region, deletion, timeout, interval):
    """
    Wait for successful stack creation or deletion.

    Supports waiting for more than one stack up to timeout seconds.
    """

    stack_refs = get_stack_refs(stack_ref)
    cf = BotoClientProxy("cloudformation", region)

    target_status = (
        ["DELETE_COMPLETE"] if deletion else ["CREATE_COMPLETE", "UPDATE_COMPLETE"]
    )

    cutoff = time.time() + timeout

    while time.time() < cutoff:
        stacks_ok = set()
        stacks_in_progress = set()
        successful_actions = set()

        stacks_found = get_stacks(stack_refs, region, all=True, unique_only=True)

        if not stacks_found:
            raise click.UsageError(
                'No matching stack for "{}" found'.format(" ".join(stack_ref))
            )

        for stack in stacks_found:

            if stack.StackStatus in target_status:
                successful_action, _ = stack.StackStatus.split("_")
                successful_actions.add("{}d".format(successful_action.lower()))
                stacks_ok.add((stack.name, stack.version))

            elif stack.StackStatus.endswith("_IN_PROGRESS"):
                stacks_in_progress.add((stack.name, stack.version, stack.StackStatus))

            else:  # _FAILED or ROLLBACK_COMPLETE or UPDATE_ROLLBACK_COMPLETE
                # output event messages for troubleshooting
                events = cf.describe_stack_events(StackName=stack.StackId)[
                    "StackEvents"
                ]
                for event in sorted(events, key=lambda x: x["Timestamp"]):
                    if failure_event(event):
                        error(
                            "ERROR: {LogicalResourceId} {ResourceStatus}: "
                            "{ResourceStatusReason}".format(**event)
                        )
                fatal_error(
                    "ERROR: Stack {}-{} has "
                    "status {}".format(stack.name, stack.version, stack.StackStatus)
                )

        if stacks_in_progress:
            waiting_for = ", ".join(
                ["{}-{} ({})".format(*x) for x in sorted(stacks_in_progress)]
            )
            info(
                "Waiting up to {:.0f} more secs "
                "for stack{} {}..".format(
                    cutoff - time.time(),
                    "s" if len(stacks_in_progress) > 1 else "",
                    waiting_for,
                )
            )
            time.sleep(interval)
            continue
        if stacks_ok:
            successful_stacks = ", ".join(
                ["{}-{}".format(*x) for x in sorted(stacks_ok)]
            )
            actions = "/".join(successful_actions)
            ok("OK: Stack(s) {} {} successfully.".format(successful_stacks, actions))
            return
    raise click.Abort()


cli.add_command(cmd_config)


def main():
    HandleExceptions(cli)()


if __name__ == "__main__":
    main()
