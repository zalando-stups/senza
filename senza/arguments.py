import click
import re

from .error_handling import HandleExceptions

REGION_PATTERN = re.compile(r'^[a-z]{2}-[a-z]+-[0-9]$')


def validate_region(ctx, param, value):
    """Validate Click region param parameter."""
    if value is not None:
        if not REGION_PATTERN.match(value):
            raise click.BadParameter("'{}'. Region must be a valid "
                                     "AWS region.".format(value))
    return value


def set_stacktrace_visible(ctx, param, value):
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
