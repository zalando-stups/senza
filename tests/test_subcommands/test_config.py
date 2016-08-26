from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner
from senza.cli import cli
from senza.exceptions import InvalidConfigKey


@pytest.fixture()
def mock_configuration(monkeypatch):
    mock = MagicMock()
    mock.dict = {"section.key": "value"}

    def get(key):
        if '.' not in key:
            raise InvalidConfigKey("Key Error")
        return mock.dict[key]

    def setitem(key, value):
        if '.' not in key:
            raise InvalidConfigKey("Key Error")
        mock.dict[key] = value

    mock.__getitem__.side_effect = get
    mock.__setitem__.side_effect = setitem

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

    assert result.output == ''
    assert result.exit_code == 1


def test_get_config_no_section(mock_configuration):
    runner = CliRunner()

    result = runner.invoke(cli,
                           ['config', '404'],
                           catch_exceptions=False)

    assert "Error: Key Error" in result.output


def test_set_config(mock_configuration):
    runner = CliRunner()

    result = runner.invoke(cli,
                           ['config', 'section.new', 'value'],
                           catch_exceptions=False)

    assert result.exit_code == 0
    assert mock_configuration['section.new'] == 'value'


def test_set_config_no_section(mock_configuration):
    runner = CliRunner()

    result = runner.invoke(cli,
                           ['config', 'new', 'value'],
                           catch_exceptions=False)

    assert "Error: Key Error" in result.output
