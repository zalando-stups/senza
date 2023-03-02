"""
Functions and decorators related to command line arguments
"""

# invalid-name is disabled to match the style of other click options
# pylint: disable=locally-disabled, invalid-name
import boto3.session
import click
import configparser
import os

from .error_handling import HandleExceptions


def get_region(region):
    """
    Ensure region value.
    If region is not provided, get one from the config file.
    Raise error if still no region is set at the end.
    """
    if not region:
        config = configparser.ConfigParser()
        try:
            config.read(os.path.expanduser("~/.aws/config"))
            if "default" in config:
                region = config["default"]["region"]
        except Exception:
            pass

    if not region:
        raise click.UsageError(
            "Please specify the AWS region on the "
            "command line (--region) or in ~/.aws/config"
        )

    return region


def validate_region(ctx, param, value):  # pylint: disable=locally-disabled, unused-argument
    """Validate Click region parameter."""

    value = get_region(value)  # ensure region is set

    session = boto3.session.Session()
    valid_regions = session.get_available_regions('cloudformation')
    if value not in valid_regions:
        valid_regions.sort()
        raise click.BadParameter("'{}'. Region must be one of the "
                                 "following AWS regions:\n"
                                 "  - {}".format(value,
                                                 "\n  - ".join(valid_regions)))

    return value


def set_stacktrace_visible(ctx, param, value):  # pylint: disable=locally-disabled, unused-argument
    """
    Callback to define whether to display the stacktrace in case of an
    unhandled error.
    """
    HandleExceptions.stacktrace_visible = value


region_option = click.option('--region',
                             envvar='AWS_DEFAULT_REGION',
                             metavar='AWS_REGION_ID',
                             help='AWS region ID (e.g. eu-west-1)',
                             callback=validate_region)

parameter_file_option = click.option('--parameter-file',
                                     help='Config file for params',
                                     metavar='PATH')

output_option = click.option('-o', '--output',
                             type=click.Choice(['text', 'json', 'tsv']),
                             default='text',
                             help='Use alternative output format')

json_output_option = click.option('-o', '--output',
                                  type=click.Choice(['json', 'yaml']),
                                  default='json',
                                  help='Use alternative output format')

stacktrace_visible_option = click.option('--stacktrace-visible',
                                         is_flag=True,
                                         callback=set_stacktrace_visible,
                                         expose_value=False,
                                         help='Show stack trace instead of '
                                              'storing it')

watch_option = click.option('-W',
                            is_flag=True,
                            help='Auto update the screen every 2 seconds')

watchrefresh_option = click.option('-w', '--watch',
                                   type=click.IntRange(1, 300),
                                   metavar='SECS',
                                   help='Auto update the screen every X seconds')

field_option = click.option('--field',
                            '-f',
                            metavar='NAME',
                            multiple=True,
                            help='Specify field to be returned')
