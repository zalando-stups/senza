import yaml
from click import get_app_dir
from click.testing import CliRunner
from senza.cli import cli


def create_config():
    app_dir = get_app_dir("senza")
    with open(app_dir + '/config.yaml', 'w+') as fd:
        fd.write('{"section": {"key": "value"}}')


def read_config():
    app_dir = get_app_dir("senza")
    with open(app_dir + '/config.yaml', 'r') as fd:
        data = yaml.safe_load(fd)
    return data


def test_get_config():
    runner = CliRunner()

    with runner.isolated_filesystem():
        create_config()
        result = runner.invoke(cli,
                               ['config', 'section.key'],
                               catch_exceptions=False)

    assert result.output == 'value\n'


def test_get_config_not_found():
    runner = CliRunner()

    with runner.isolated_filesystem():
        create_config()
        result = runner.invoke(cli,
                               ['config', 'section.404'],
                               catch_exceptions=False)

    assert result.output == ''
    assert result.exit_code == 1


def test_get_config_no_section():
    runner = CliRunner()

    with runner.isolated_filesystem():
        create_config()
        result = runner.invoke(cli,
                               ['config', '404'],
                               catch_exceptions=False)

    assert "Error: key does not contain a section" in result.output


def test_set_config():
    runner = CliRunner()

    with runner.isolated_filesystem():
        create_config()
        result = runner.invoke(cli,
                               ['config', 'section.new', 'value'],
                               catch_exceptions=False)
        new_config = read_config()

    assert new_config['section']['new'] == 'value'
    assert result.exit_code == 0


def test_set_config_no_section():
    runner = CliRunner()

    with runner.isolated_filesystem():
        create_config()
        result = runner.invoke(cli,
                               ['config', 'new', 'value'],
                               catch_exceptions=False)

    assert "Error: key does not contain a section" in result.output
