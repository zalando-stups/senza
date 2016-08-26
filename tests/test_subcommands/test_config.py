import pytest
from click.testing import CliRunner
from senza.cli import cli


@pytest.fixture()
def mock_configuration(monkeypatch):
    mock = {"section.key": "value"}
    monkeypatch.setattr('senza.subcommands.config.configuration', mock)
    return mock


def test_get_config(mock_configuration):
    runner = CliRunner()

    result = runner.invoke(cli,
                           ['config', 'section.key'],
                           catch_exceptions=False)

    assert result.output == 'value\n'


def test_get_config_not_found(mock_configuration):
    runner = CliRunner()

    result = runner.invoke(cli,
                           ['config', 'section.404'],
                           catch_exceptions=False)

    assert "key doesn't contain a section: section.404" in result.output


def test_set_config(mock_configuration):
    runner = CliRunner()

    result = runner.invoke(cli,
                           ['config', 'section.new', 'value'],
                           catch_exceptions=False)

    assert result.exit_code == 0
    assert mock_configuration['section.new'] == 'value'
