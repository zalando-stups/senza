import inspect
import random
import string
from unittest.mock import MagicMock

import botocore.exceptions
import senza.error_handling
import yaml
from pytest import fixture, raises
from senza.exceptions import PiuNotFound
from senza.manaus.exceptions import ELBNotFound, InvalidState


def lineno() -> int:
    """
    Returns the current line number.
    Needed to make sure the expected exceptions stack traces are always updated
    """
    return inspect.currentframe().f_back.f_lineno


def generate_fake_filename() -> str:
    return ''.join(random.choice(string.ascii_uppercase + string.digits)
                   for _ in range(10))


@fixture()
def mock_tempfile(monkeypatch):
    random_name = generate_fake_filename()
    mock = MagicMock(name=random_name)

    mock.__enter__.return_value = mock
    mock.return_value = mock
    monkeypatch.setattr('senza.error_handling.NamedTemporaryFile', mock)
    return mock


@fixture()
def mock_raven(monkeypatch):
    mock = MagicMock()
    mock.return_value = mock
    monkeypatch.setattr('senza.error_handling.Client', mock)
    return mock


def test_store_exception(monkeypatch, mock_tempfile):

    line_n = lineno() + 2
    try:
        raise Exception("Testing exception handing")
    except Exception as e:
        file_name = senza.error_handling.store_exception(e)

    lines = ['Traceback (most recent call last):',
             '  File "{}", line {}, in test_store_exception'.format(__file__, line_n),
             '    raise Exception("Testing exception handing")',
             'Exception: Testing exception handing\n']

    expected_exception = '\n'.join(lines).encode()

    mock_tempfile.assert_called_once_with(prefix='senza-traceback-',
                                          delete=False)
    assert file_name == mock_tempfile.name
    mock_tempfile.write.assert_called_once_with(expected_exception)


def test_store_nested_exception(monkeypatch, mock_tempfile):

    line_n1 = lineno() + 2
    try:
        raise Exception("Testing exception handing")
    except Exception as e:
        line_n2 = lineno() + 2
        try:
            raise Exception("Testing nested exception handing")
        except Exception as e:
            file_name = senza.error_handling.store_exception(e)

    lines = ['Traceback (most recent call last):',
             '  File "{}", line {}, in test_store_nested_exception'.format(__file__, line_n1),
             '    raise Exception("Testing exception handing")',
             'Exception: Testing exception handing',
             '',
             'During handling of the above exception, another exception occurred:',
             '',
             'Traceback (most recent call last):',
             '  File "{}", line {}, in test_store_nested_exception'.format(__file__, line_n2),
             '    raise Exception("Testing nested exception handing")',
             "Exception: Testing nested exception handing\n"]

    expected_exception = '\n'.join(lines).encode()

    mock_tempfile.assert_called_once_with(prefix='senza-traceback-',
                                          delete=False)
    assert file_name == mock_tempfile.name
    mock_tempfile.write.assert_called_once_with(expected_exception)


def test_missing_credentials(capsys):
    func = MagicMock(side_effect=botocore.exceptions.NoCredentialsError())

    try:
        senza.error_handling.HandleExceptions(func)()
    except SystemExit:
        pass

    out, err = capsys.readouterr()
    assert 'No AWS credentials found.' in err

    func = MagicMock(side_effect=botocore.exceptions.ClientError(
        {'Error': {'Code': 'AccessDenied',
                   'Message': 'User: myuser is not authorized to perform: service:TaskName'}},
        'foobar'))

    try:
        senza.error_handling.HandleExceptions(func)()
    except SystemExit:
        pass

    out, err = capsys.readouterr()

    assert 'No AWS credentials found.' in err


def test_expired_credentials(capsys):
    func = MagicMock(side_effect=botocore.exceptions.ClientError(
        {'Error': {'Code': 'ExpiredToken',
                   'Message': 'Token expired'}},
        'foobar'))

    try:
        senza.error_handling.HandleExceptions(func)()
    except SystemExit:
        pass

    out, err = capsys.readouterr()

    assert 'AWS credentials have expired.' in err


def test_unknown_ClientError_raven(capsys, mock_raven):
    senza.error_handling.sentry = senza.error_handling.setup_sentry('test')
    func = MagicMock(side_effect=botocore.exceptions.ClientError(
        {'Error': {'Code': 'SomeUnknownError',
                   'Message': 'A weird error happened'}},
        'foobar'))

    try:
        senza.error_handling.HandleExceptions(func)()
    except SystemExit:
        pass

    mock_raven.captureException.assert_called_once_with()


def test_unknown_ClientError_no_stack_trace(capsys, mock_raven):
    senza.error_handling.sentry = senza.error_handling.setup_sentry(None)
    func = MagicMock(side_effect=botocore.exceptions.ClientError(
        {'Error': {'Code': 'SomeUnknownError',
                   'Message': 'A weird error happened'}},
        'foobar'))

    try:
        senza.error_handling.HandleExceptions(func)()
    except SystemExit:
        pass

    out, err = capsys.readouterr()

    assert 'Unknown Error: An error occurred' in err


def test_piu_not_found(capsys):
    func = MagicMock(side_effect=PiuNotFound())

    try:
        senza.error_handling.HandleExceptions(func)()
    except SystemExit:
        pass

    out, err = capsys.readouterr()

    assert "Command not found: piu" in err


def test_elb_not_found(capsys):
    func = MagicMock(side_effect=ELBNotFound('example.com'))

    try:
        senza.error_handling.HandleExceptions(func)()
    except SystemExit:
        pass

    out, err = capsys.readouterr()

    assert err == 'ELB not found: example.com\n'


def test_invalid_state(capsys):
    func = MagicMock(side_effect=InvalidState('test state'))

    try:
        senza.error_handling.HandleExceptions(func)()
    except SystemExit:
        pass

    out, err = capsys.readouterr()

    assert err == 'Invalid State: test state\n'


def test_validation(capsys):
    func = MagicMock(side_effect=botocore.exceptions.ClientError(
        {'Error': {'Code': 'ValidationError',
                   'Message': 'Validation Error'}},
        'foobar'))

    try:
        senza.error_handling.HandleExceptions(func)()
    except SystemExit:
        pass

    out, err = capsys.readouterr()

    assert err == 'Validation Error: Validation Error\n'


def test_yaml_error(capsys):
    def func():
        return yaml.load("[]: value")
    try:
        senza.error_handling.HandleExceptions(func)()
    except SystemExit:
        pass

    out, err = capsys.readouterr()

    assert 'Error parsing definition file:' in err
    assert 'found unhashable key' in err
    assert 'Please quote all variable values' in err


def test_unknown_error(capsys, mock_tempfile, mock_raven):
    senza.error_handling.sentry = senza.error_handling.setup_sentry(None)
    func = MagicMock(side_effect=Exception("something"))
    try:
        senza.error_handling.HandleExceptions(func)()
    except SystemExit:
        pass

    out, err = capsys.readouterr()

    mock_tempfile.assert_called_once_with(prefix='senza-traceback-',
                                          delete=False)

    assert 'Unknown Error: something.' in err


def test_unknown_error_sentry(capsys, mock_tempfile, mock_raven):
    senza.error_handling.sentry = senza.error_handling.setup_sentry("test")
    func = MagicMock(side_effect=Exception("something"))
    try:
        senza.error_handling.HandleExceptions(func)()
    except SystemExit:
        pass

    mock_tempfile.assert_not_called()
    mock_raven.captureException.assert_called_once_with()


def test_unknown_error_show_stacktrace(mock_tempfile, mock_raven):
    senza.error_handling.sentry = senza.error_handling.setup_sentry("test")
    senza.error_handling.HandleExceptions.stacktrace_visible = True
    func = MagicMock(side_effect=Exception("something"))
    with raises(Exception, message="something"):
        senza.error_handling.HandleExceptions(func)()

    mock_tempfile.assert_not_called()
    mock_raven.captureException.assert_called_once_with()
