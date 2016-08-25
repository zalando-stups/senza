from unittest.mock import MagicMock

import pytest
from senza.exceptions import PiuNotFound
from senza.stups.piu import Piu


def test_request_access(monkeypatch):
    m_call = MagicMock()
    monkeypatch.setattr('senza.stups.piu.call', m_call)

    Piu.request_access('127.0.0.1', 'no reason', None, True)
    m_call.assert_called_once_with(['piu', 'request-access',
                                    '127.0.0.1', 'no reason via senza',
                                    '--connect'])

    m_call.reset_mock()
    Piu.request_access('127.0.0.1', 'no reason', None, False)
    m_call.assert_called_once_with(['piu', 'request-access',
                                    '127.0.0.1', 'no reason via senza'])

    m_call.reset_mock()
    Piu.request_access('127.0.0.1', 'no reason', 'example.com', True)
    m_call.assert_called_once_with(['piu', 'request-access',
                                    '127.0.0.1', 'no reason via senza',
                                    '--connect',
                                    '-O', 'example.com'])


def test_find_odd_host(monkeypatch):
    m_client = MagicMock()
    m_client.return_value = m_client
    hosted_zone1 = {'Config': {'PrivateZone': False},
                    'CallerReference': '0000',
                    'ResourceRecordSetCount': 42,
                    'Id': '/hostedzone/random1',
                    'Name': 'example.com.'}
    mock_records = [{'Name': 'odd-eu-west-1.example.com.',
                     'ResourceRecords': [{'Value': '127.0.0.1'}],
                     'TTL': 600,
                     'Type': 'A'}
                    ]
    m_client.list_hosted_zones.return_value = {'MaxItems': '100',
                                               'ResponseMetadata': {
                                                   'HTTPStatusCode': 200,
                                                   'RequestId': 'FakeId'},
                                               'HostedZones': [hosted_zone1],
                                               'IsTcallcated': False}
    m_client.list_resource_record_sets.return_value = {
        "ResourceRecordSets": mock_records}
    monkeypatch.setattr('boto3.client', m_client)

    odd_host = Piu.find_odd_host('eu-west-1')
    assert odd_host == 'odd-eu-west-1.example.com'

    no_odd_host = Piu.find_odd_host('moon-crater-1')
    assert no_odd_host is None


def test_request_access_not_installed(monkeypatch):
    m_call = MagicMock()
    m_call.side_effect = FileNotFoundError
    monkeypatch.setattr('senza.stups.piu.call', m_call)

    with pytest.raises(PiuNotFound):
        Piu.request_access('127.0.0.1', 'no reason', None, True)
    m_call.assert_called_once_with(['piu', 'request-access',
                                    '127.0.0.1', 'no reason via senza',
                                    '--connect'])
