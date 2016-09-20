from unittest.mock import MagicMock

from click.testing import CliRunner
from senza.subcommands.root import check_senza_version, cli

from fixtures import disable_version_check  # noqa: F401


def test_check_senza_version(monkeypatch):
    mock_warning = MagicMock()
    mock_get = MagicMock()
    mock_get.return_value = mock_get
    mock_get.json.return_value = {'releases': {'0.29': None,
                                               '0.42': None,
                                               '0.7': None}}
    monkeypatch.setattr("senza.subcommands.root.warning", mock_warning)
    monkeypatch.setattr("senza.subcommands.root.requests.get", mock_get)
    check_senza_version("0.42")
    mock_warning.assert_not_called()

    check_senza_version("0.43")
    mock_warning.assert_not_called()

    check_senza_version("0.40")
    mock_warning.assert_called_once_with(
        "Your senza version (0.40) is outdated. "
        "Please install the new one using 'pip install --upgrade stups-senza'"
    )

    mock_warning.reset_mock()
    monkeypatch.setattr("senza.subcommands.root.__file__",
                        '/usr/pymodules/root.py')
    check_senza_version("0.40")
    mock_warning.assert_called_once_with(
        "Your senza version (0.40) is outdated. "
        "Please install the new one using "
        "'sudo pip install --upgrade stups-senza'"
    )


def test_version(disable_version_check):  # noqa: F811
    runner = CliRunner()
    result = runner.invoke(cli, ['--version'])
    assert result.output.startswith('Senza ')
