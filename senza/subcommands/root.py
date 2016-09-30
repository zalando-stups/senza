"""
Senza's root command with tasks and flags common to all sub-commands
"""

import sys
import time
from distutils.version import LooseVersion
from pathlib import Path
from typing import Optional

import click
import requests
import senza
from clickclick import AliasedGroup, warning

from ..arguments import GLOBAL_OPTIONS, region_option
from ..error_handling import sentry

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])

PYPI_URL = "https://pypi.python.org/pypi/stups-senza/json"
ONE_DAY = 86400  # seconds


def get_latest_version_from_disk() -> Optional[LooseVersion]:
    """
    Tries to read a cached latest version from the disk returning None if the
    file doesn't exist or if it's older than 24 hours
    """
    version_cache = Path(click.get_app_dir('senza')) / 'pypi_version'
    now = time.time()
    latest_version = None
    if (version_cache.exists() and
            now - version_cache.stat().st_mtime < ONE_DAY):
        with version_cache.open() as version_cache_file:
            str_version = version_cache_file.read()
            if str_version:
                latest_version = LooseVersion(str_version)
    return latest_version


def get_latest_version_from_pypi() -> Optional[LooseVersion]:
    """
    Gets the latest release version pypi api using distutils order
    to sort the releases (same as pip).
    """
    try:
        pypi_response = requests.get(PYPI_URL, timeout=1)
    except requests.Timeout:
        return None

    # the potential exception is not caught here but it's caught in
    # check_senza_version and pushed to sentry if it is configured
    pypi_response.raise_for_status()
    pypi_data = pypi_response.json()
    releases = pypi_data['releases']
    versions = [LooseVersion(version) for version in releases.keys()]
    return sorted(versions)[-1]


def get_latest_version() -> Optional[LooseVersion]:
    """
    Gets the latest version either from the file cache or from pip.

    If the file cache exists it will be valid for 24 hours.
    """
    version_cache = Path(click.get_app_dir('senza')) / 'pypi_version'
    latest_version = (get_latest_version_from_disk() or
                      get_latest_version_from_pypi())

    if latest_version is not None:
        try:
            version_cache.parent.mkdir(parents=True)
        except FileExistsError:
            # this try...except can be replaced with exist_ok=True when
            # we drop python3.4 support
            pass

        with version_cache.open('w') as version_cache_file:
            version_cache_file.write(str(latest_version))
    return latest_version


def check_senza_version(current_version: str):
    """
    Checks if senza is updated and prints a warning with instructions to update
    if it's not.
    """
    if not sys.stdout.isatty():
        return
    current_version = LooseVersion(current_version)
    try:
        latest_version = get_latest_version()
    except Exception:
        if sentry is not None:
            sentry.captureException()
        return

    if latest_version is not None and current_version < latest_version:
        if __file__.startswith('/home'):
            # if it's installed in the user folder
            cmd = "pip install --upgrade stups-senza"
        else:
            cmd = "sudo pip install --upgrade stups-senza"
        warning("Your senza version ({current}) is outdated. "
                "Please install the new one using '{cmd}'".format(current=current_version,
                                                                  cmd=cmd))


def print_version(ctx, param, value):
    """
    Prints current senza version and checks if it's the latest one.
    """
    assert param.name == "version"
    if not value or ctx.resilient_parsing:
        return

    click.echo('Senza {}'.format(senza.__version__))
    # this needs to be here since when this is called cli() is not
    check_senza_version(senza.__version__)
    ctx.exit()


@click.group(cls=AliasedGroup, context_settings=CONTEXT_SETTINGS)
@click.option('-V', '--version',
              is_flag=True, callback=print_version, expose_value=False,
              is_eager=True,
              help='Print the current version number and exit.')
@region_option
def cli(region):
    """
    Senza's root command.

    It checks the version and sets the region global option before executing
    the sub-commands.

    Sub command can be added by using `cli.add_command(SUB_COMMAND_FUNCTION)`
    or using the `@cli.command()` decorator
    """
    check_senza_version(senza.__version__)
    GLOBAL_OPTIONS['region'] = region
