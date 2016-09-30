from tempfile import TemporaryDirectory
from unittest.mock import MagicMock

from click.testing import CliRunner
from pytest import fixture
from requests.exceptions import HTTPError, Timeout
from senza.subcommands.root import check_senza_version, cli

from fixtures import disable_version_check  # noqa: F401


@fixture()
def mock_get_app_dir(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("senza.subcommands.root.click.get_app_dir", mock)
    return mock


@fixture()
def mock_get(monkeypatch):
    mock = MagicMock()
    mock.return_value = mock
    mock.json.return_value = {'releases': {'0.29': None,
                                           '0.42': None,
                                           '0.7': None}}
    monkeypatch.setattr("senza.subcommands.root.requests.get", mock)
    return mock


@fixture()
def mock_warning(monkeypatch):
    mock = MagicMock()
    monkeypatch.setattr("senza.subcommands.root.warning", mock)
    return mock


@fixture()
def mock_tty(monkeypatch):
    # check_senza_version only prints if we have a TTY
    monkeypatch.setattr('sys.stdout.isatty', lambda: True)


def test_check_senza_version_notty(monkeypatch, mock_get_app_dir, mock_get, mock_warning):
    with TemporaryDirectory() as temp_dir:
        mock_get_app_dir.return_value = temp_dir
        monkeypatch.setattr("senza.subcommands.root.__file__",
                            '/home/someuser/pymodules/root.py')
        check_senza_version("0.40")
        mock_warning.assert_not_called()


def test_check_senza_version(monkeypatch,
                             mock_get_app_dir, mock_get, mock_warning, mock_tty):

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
        monkeypatch.setattr("senza.subcommands.root.__file__",
                            '/home/someuser/pymodules/root.py')
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


def test_check_senza_version_timeout(mock_get_app_dir, mock_get, mock_warning, mock_tty):
    with TemporaryDirectory() as temp_dir:
        mock_get_app_dir.return_value = temp_dir
        mock_get.side_effect = Timeout
        check_senza_version("0.2")
        mock_warning.assert_not_called()


def test_check_senza_version_outdated_cache(monkeypatch,  # noqa: F811
                                            mock_get_app_dir,
                                            mock_get,
                                            mock_warning,
                                            mock_tty):
    monkeypatch.setattr("senza.subcommands.root.__file__",
                        '/usr/pymodules/root.py')
    with TemporaryDirectory() as temp_dir:
        mock_get_app_dir.return_value = temp_dir
        with open(temp_dir + '/pypi_version', 'w') as fd:
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


def test_check_senza_version_exception(monkeypatch,
                                       mock_get_app_dir,
                                       mock_get,
                                       mock_warning,
                                       mock_tty):
    mock_sentry = MagicMock()
    monkeypatch.setattr("senza.subcommands.root.sentry", mock_sentry)
    with TemporaryDirectory() as temp_dir:
        mock_get_app_dir.return_value = temp_dir
        mock_get.raise_for_status.side_effect = HTTPError(404, "Not Found")
        check_senza_version("0.2")
        mock_warning.assert_not_called()
        mock_sentry.captureException.assert_called_once_with()

    monkeypatch.setattr("senza.subcommands.root.sentry", None)
    with TemporaryDirectory() as temp_dir:
        mock_get_app_dir.return_value = temp_dir
        mock_get.raise_for_status.side_effect = HTTPError(404, "Not Found")
        check_senza_version("0.2")
        mock_warning.assert_not_called()


def test_version(disable_version_check):  # noqa: F811
    runner = CliRunner()
    result = runner.invoke(cli, ['--version'])
    assert result.output.startswith('Senza ')
