from unittest.mock import MagicMock

from senza.stups.piu import Piu

def test_route53_hosted_zones(monkeypatch):
    m_client = MagicMock()
    m_client.return_value = m_client
    hosted_zone1 = {'Config': {'PrivateZone': False},
                    'CallerReference': '0000',
                    'ResourceRecordSetCount': 42,
                    'Id': '/hostedzone/random1',
                    'Name': 'example.com.'}
    hosted_zone2 = {'Config': {'PrivateZone': False},
                    'CallerReference': '0000',
                    'ResourceRecordSetCount': 7,
                    'Id': '/hostedzone/random2',
                    'Name': 'example.net.'}
    m_client.list_hosted_zones.return_value = {'MaxItems': '100',
                                               'ResponseMetadata': {
                                                   'HTTPStatusCode': 200,
                                                   'RequestId': 'FakeId'},
                                               'HostedZones': [hosted_zone1],
                                               'IsTruncated': False}
    monkeypatch.setattr('boto3.client', m_client)

    odd_host = Piu.find_odd_host('eu-west-1')
    assert odd_host == 'odd-eu-west-1.example.com'
