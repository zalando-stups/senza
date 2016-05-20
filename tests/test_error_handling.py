from unittest.mock import MagicMock
import inspect
import random
import string

from pytest import fixture

import senza.error_handling


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


def test_store_exception(monkeypatch, mock_tempfile):

    line_n = lineno() + 2
    try:
        _ = 0/0
    except Exception as e:
        file_name = senza.error_handling.store_exception(e)

    lines = ['Traceback (most recent call last):',
             '  File "{}", line {}, in test_store_exception'.format(__file__, line_n),
             '    _ = 0/0',
             'ZeroDivisionError: division by zero\n']

    expected_exception = '\n'.join(lines).encode()

    mock_tempfile.assert_called_once_with(prefix='senza-traceback-',
                                          delete=False)
    assert file_name == mock_tempfile.name
    mock_tempfile.write.assert_called_once_with(expected_exception)


def test_store_nested_exception(monkeypatch, mock_tempfile):

    line_n1 = lineno() + 2
    try:
        _ = 0/0
    except Exception as e:
        line_n2 = lineno() + 2
        try:
            _ = "a" + 0
        except Exception as e:
            file_name = senza.error_handling.store_exception(e)

    lines = ['Traceback (most recent call last):',
             '  File "{}", line {}, in test_store_nested_exception'.format(__file__, line_n1),
             '    _ = 0/0',
             'ZeroDivisionError: division by zero',
             '',
             'During handling of the above exception, another exception occurred:',
             '',
             'Traceback (most recent call last):',
             '  File "{}", line {}, in test_store_nested_exception'.format(__file__, line_n2),
             '    _ = "a" + 0',
             "TypeError: Can't convert 'int' object to str implicitly\n"]

    expected_exception = '\n'.join(lines).encode()

    mock_tempfile.assert_called_once_with(prefix='senza-traceback-',
                                          delete=False)
    assert file_name == mock_tempfile.name
    mock_tempfile.write.assert_called_once_with(expected_exception)




