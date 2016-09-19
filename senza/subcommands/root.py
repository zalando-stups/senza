from distutils.version import LooseVersion

import click
import requests
import senza
from clickclick import AliasedGroup, warning

from ..arguments import GLOBAL_OPTIONS, region_option

CONTEXT_SETTINGS = dict(help_option_names=['-h', '--help'])


def check_senza_version(current_version):
    # TODO move to own module

    current_version = LooseVersion(current_version)

    url = "https://pypi.python.org/pypi/stups-senza/json"
    pypi_response = requests.get(url)
    pypi_data = pypi_response.json()
    releases = pypi_data['releases']
    versions = [LooseVersion(version) for version in releases.keys()]
    last_version = sorted(versions)[-1]
    if current_version < last_version:
        if __file__.startswith('/home'):
            # if it's installed in the user folder
            cmd = "pip install --upgrade stups-senza"
        else:
            cmd = "sudo pip install --upgrade stups-senza"
        warning("Your senza version ({current}) is outdated. "
                "Please install the new one using '{cmd}'".format(current=current_version,
                                                                  cmd=cmd))

def print_version(ctx, param, value):
    if not value or ctx.resilient_parsing:
        return

    click.echo('Senza {}'.format(senza.__version__))
    # this needs to be here since when this is called cli() is not
    check_senza_version(senza.__version__)
    ctx.exit()


@click.group(cls=AliasedGroup, context_settings=CONTEXT_SETTINGS)
@click.option('-V', '--version', is_flag=True, callback=print_version, expose_value=False, is_eager=True,
              help='Print the current version number and exit.')
@region_option
def cli(region):
    check_senza_version(senza.__version__)
    GLOBAL_OPTIONS['region'] = region
