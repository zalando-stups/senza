from unittest.mock import MagicMock

import botocore.exceptions
import pytest
from senza.manaus.boto_proxy import BotoClientProxy


@pytest.fixture(autouse=True)
def mock_boto_client(monkeypatch):
    m = MagicMock(p=42)
    m.return_value = m
    monkeypatch.setattr('boto3.client', m)
    return m


def test_proxy(mock_boto_client: MagicMock):
    proxy = BotoClientProxy('test')
    mock_boto_client.assert_called_once_with('test')
    proxy.random_test(42)
    mock_boto_client.random_test.assert_called_once_with(42)
    assert proxy.random_test is not mock_boto_client.random_test
    assert proxy.p is mock_boto_client.p


def test_throttling(mock_boto_client: MagicMock, monkeypatch):
    monkeypatch.setattr('senza.manaus.boto_proxy.sleep', MagicMock())
    i = 0

    def throttled(arg):
        nonlocal i
        if i < 3:
            i += 1
            raise botocore.exceptions.ClientError(
                {'Error': {'Code': 'Throttling'}},
                'testing'
            )
        else:
            return arg

    mock_boto_client.throttled.side_effect = throttled
    proxy = BotoClientProxy('test')
    mock_boto_client.assert_called_once_with('test')
    assert proxy.throttled(42) == 42
    mock_boto_client.throttled.assert_called_with(42)
    assert mock_boto_client.throttled.call_count == 4


def test_throttling_forever(mock_boto_client: MagicMock, monkeypatch):
    monkeypatch.setattr('senza.manaus.boto_proxy.sleep', MagicMock())

    def throttled(arg):
        raise botocore.exceptions.ClientError(
            {'Error': {'Code': 'Throttling'}},
            'testing'
        )

    mock_boto_client.throttled.side_effect = throttled
    proxy = BotoClientProxy('test')

    with pytest.raises(botocore.exceptions.ClientError):
        proxy.throttled(42)
    mock_boto_client.throttled.assert_called_with(42)
    assert mock_boto_client.throttled.call_count == 5


def test_random_error(mock_boto_client: MagicMock, monkeypatch):
    monkeypatch.setattr('senza.manaus.boto_proxy.sleep', MagicMock())

    def throttled(arg):
        raise botocore.exceptions.ClientError(
            {'Error': {'Code': "everyday i'm shuffling"}},
            'testing'
        )

    mock_boto_client.throttled.side_effect = throttled
    proxy = BotoClientProxy('test')

    with pytest.raises(botocore.exceptions.ClientError):
        proxy.throttled(42)
    mock_boto_client.throttled.assert_called_with(42)
    assert mock_boto_client.throttled.call_count == 1
