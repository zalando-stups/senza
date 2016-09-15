from pathlib import Path
from os import makedirs

import yaml
from click.testing import CliRunner
from senza.cli import cli
from senza.subcommands.config import configuration


def create_config(app_dir):
    configuration.config_path = Path(app_dir) / 'config.yaml'
    makedirs(app_dir, exist_ok=True)
    with configuration.config_path.open('w+') as fd:
        fd.write('{"section": {"key": "value"}}')


def read_config(app_dir):
    config_path = Path(app_dir) / 'config.yaml'
    with config_path.open() as fd:
        data = yaml.safe_load(fd)
    return data


def test_get_config():
    runner = CliRunner()

    with runner.isolated_filesystem() as (test_dir):
        create_config(test_dir)
        result = runner.invoke(cli,
                               ['config', 'section.key'],
                               catch_exceptions=False)

    assert result.output == 'value\n'


def test_get_config_not_found():
    runner = CliRunner()

    with runner.isolated_filesystem() as (test_dir):
        create_config(test_dir)
        result = runner.invoke(cli,
                               ['config', 'section.404'],
                               catch_exceptions=False)

    assert result.output == ''
    assert result.exit_code == 1


def test_get_config_no_section():
    runner = CliRunner()

    with runner.isolated_filesystem() as (test_dir):
        create_config(test_dir)
        result = runner.invoke(cli,
                               ['config', '404'],
                               catch_exceptions=False)

    assert "Error: key does not contain a section" in result.output


def test_set_config():
    runner = CliRunner()

    with runner.isolated_filesystem() as (test_dir):
        create_config(test_dir)
        result = runner.invoke(cli,
                               ['config', 'section.new', 'value'],
                               catch_exceptions=False)
        new_config = read_config(test_dir)

    assert new_config['section']['new'] == 'value'
    assert result.exit_code == 0


def test_set_config_no_section():
    runner = CliRunner()

    with runner.isolated_filesystem() as (test_dir):
        create_config(test_dir)
        result = runner.invoke(cli,
                               ['config', 'new', 'value'],
                               catch_exceptions=False)

    assert "Error: key does not contain a section" in result.output
