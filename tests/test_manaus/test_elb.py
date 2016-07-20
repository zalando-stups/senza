from unittest.mock import MagicMock

import pytest

from senza.manaus.elb import ELB


def test_get_hosted_zone(monkeypatch):
    m_client = MagicMock()
    m_client.return_value = m_client
    hosted_eu_west_1 = {'Config': {'PrivateZone': False},
                        'CallerReference': '0000',
                        'ResourceRecordSetCount': 42,
                        'Id': 'Z32O12XQLNTSW2',
                        'Name': 'example.com.'}
    hosted_zone2 = {'Config': {'PrivateZone': False},
                    'CallerReference': '0000',
                    'ResourceRecordSetCount': 7,
                    'Id': 'ZWKZPGTI48KDX',
                    'Name': 'example.net.'}
    m_client.list_hosted_zones.return_value = {'MaxItems': '100',
                                               'ResponseMetadata': {
                                                   'HTTPStatusCode': 200,
                                                   'RequestId': 'FakeId'},
                                               'HostedZones': [hosted_eu_west_1,
                                                               hosted_zone2],
                                               'IsTruncated': False}
    monkeypatch.setattr('boto3.client', m_client)

    zone1 = ELB.get_hosted_zone_for(dns_name='lb.eu-west-1.elb.amazonaws.com')
    assert zone1.id == 'Z32O12XQLNTSW2'

    zone2 = ELB.get_hosted_zone_for(region="ap-northeast-2")
    assert zone2.id == 'ZWKZPGTI48KDX'

    with pytest.raises(ValueError):
        ELB.get_hosted_zone_for(dns_name='lb.eu-west-1.elb.amazonaws.com',
                                region="ap-northeast-2")
