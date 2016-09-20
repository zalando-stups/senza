from unittest.mock import MagicMock
from tempfile import TemporaryDirectory

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
    mock_get_app_dir = MagicMock()
    monkeypatch.setattr("senza.subcommands.root.click.get_app_dir",
                        mock_get_app_dir)
    monkeypatch.setattr("senza.subcommands.root.warning", mock_warning)
    monkeypatch.setattr("senza.subcommands.root.requests.get", mock_get)

    with TemporaryDirectory() as temp_dir_1:
        mock_get_app_dir.return_value = temp_dir_1
        check_senza_version("0.42")
        mock_warning.assert_not_called()
        with open(temp_dir_1 + '/pypi_version') as fd:
            assert fd.read() == '0.42'

    with TemporaryDirectory() as temp_dir_2:
        mock_get_app_dir.return_value = temp_dir_2
        check_senza_version("0.43")
        mock_warning.assert_not_called()

    with TemporaryDirectory() as temp_dir_3:
        mock_get_app_dir.return_value = temp_dir_3
        check_senza_version("0.40")
        mock_warning.assert_called_once_with(
            "Your senza version (0.40) is outdated. "
            "Please install the new one using 'pip install --upgrade stups-senza'"
        )

    with TemporaryDirectory() as temp_dir_4:
        mock_get_app_dir.return_value = temp_dir_4
        mock_warning.reset_mock()
        monkeypatch.setattr("senza.subcommands.root.__file__",
                            '/usr/pymodules/root.py')
        check_senza_version("0.40")
        mock_warning.assert_called_once_with(
            "Your senza version (0.40) is outdated. "
            "Please install the new one using "
            "'sudo pip install --upgrade stups-senza'"
        )

    with TemporaryDirectory() as temp_dir_5:
        mock_get_app_dir.return_value = temp_dir_5
        mock_warning.reset_mock()
        with open(temp_dir_5 + '/pypi_version', 'w') as fd:
            fd.write('0.40')
        check_senza_version("0.40")  # This should use the disk cache
        mock_warning.assert_not_called()

        monkeypatch.setattr("senza.subcommands.root.ONE_DAY", 0)
        check_senza_version("0.40")  # This should use the API again
        mock_warning.assert_called_once_with(
            "Your senza version (0.40) is outdated. "
            "Please install the new one using "
            "'sudo pip install --upgrade stups-senza'"
        )


def test_version(disable_version_check):  # noqa: F811
    runner = CliRunner()
    result = runner.invoke(cli, ['--version'])
    assert result.output.startswith('Senza ')
