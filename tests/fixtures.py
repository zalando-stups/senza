from datetime import datetime
from unittest.mock import MagicMock

import pytest

CERT1_ZO_NE = {'CertificateArn': 'arn:aws:acm:eu-west-1:cert1',
               'CreatedAt': datetime(2016, 4, 1, 12, 13, 14),
               'DomainName': '*.zo.ne',
               'DomainValidationOptions': [
                   {'DomainName': '*.zo.ne',
                    'ValidationDomain': 'zo.ne',
                    'ValidationEmails': [
                        'hostmaster@zo.ne',
                        'webmaster@zo.ne',
                        'postmaster@zo.ne',
                        'admin@zo.ne',
                        'administrator@zo.ne']}, ],
               'InUseBy': ['arn:aws:elasticloadbalancing:eu-west-1:lb'],
               'IssuedAt': datetime(2016, 4, 1, 12, 14, 14),
               'Issuer': 'SenzaTest',
               'KeyAlgorithm': 'RSA-2048',
               'NotAfter': datetime(2017, 4, 1, 12, 14, 14),
               'NotBefore': datetime(2016, 4, 1, 12, 14, 14),
               'Serial': '00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00',
               'SignatureAlgorithm': 'SHA256WITHRSA',
               'Status': 'ISSUED',
               'Subject': 'CN=*.zo.ne',
               'SubjectAlternativeNames': []}

CERT1_ZO_NE_REVOKED = {'CertificateArn': 'arn:aws:acm:eu-west-1:cert1',
                       'CreatedAt': datetime(2016, 4, 1, 12, 13, 14),
                       'DomainName': '*.zo.ne',
                       'DomainValidationOptions': [
                           {'DomainName': '*.zo.ne',
                            'ValidationDomain': 'zo.ne',
                            'ValidationEmails': [
                                'hostmaster@zo.ne',
                                'webmaster@zo.ne',
                                'postmaster@zo.ne',
                                'admin@zo.ne',
                                'administrator@zo.ne']}, ],
                       'InUseBy': [
                           'arn:aws:elasticloadbalancing:eu-west-1:lb'],
                       'IssuedAt': datetime(2016, 4, 1, 12, 14, 14),
                       'Issuer': 'SenzaTest',
                       'KeyAlgorithm': 'RSA-2048',
                       'NotAfter': datetime(2017, 4, 1, 12, 14, 14),
                       'NotBefore': datetime(2016, 4, 1, 12, 14, 14),
                       'Serial': '00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00',
                       'SignatureAlgorithm': 'SHA256WITHRSA',
                       'Status': 'REVOKED',
                       'Subject': 'CN=*.zo.ne',
                       'SubjectAlternativeNames': []}

HOSTED_ZONE_EXAMPLE_NET = {'Config': {'PrivateZone': False},
                           'CallerReference': '0000',
                           'ResourceRecordSetCount': 42,
                           'Id': '/hostedzone/123',
                           'Name': 'example.net.'}

HOSTED_ZONE_EXAMPLE_ORG = {'Config': {'PrivateZone': False},
                           'CallerReference': '0000',
                           'ResourceRecordSetCount': 42,
                           'Id': '/hostedzone/123',
                           'Name': 'example.org.'}

HOSTED_ZONE_ZO_NE = {'Config': {'PrivateZone': False},
                     'CallerReference': '0000',
                     'ResourceRecordSetCount': 23,
                     'Id': '/hostedzone/123456',
                     'Name': 'zo.ne.'}

HOSTED_ZONE_ZO_NE_COM = {'Config': {'PrivateZone': False},
                         'CallerReference': '0000',
                         'ResourceRecordSetCount': 23,
                         'Id': '/hostedzone/123456',
                         'Name': 'zo.ne.com.'}

HOSTED_ZONE_ZO_NE_DEV = {'Config': {'PrivateZone': False},
                         'CallerReference': '0000',
                         'ResourceRecordSetCount': 23,
                         'Id': '/hostedzone/123456',
                         'Name': 'zo.ne.dev.'}


@pytest.fixture
def boto_client(monkeypatch):
    def my_client(rtype, *args):
        if rtype == 'route53':
            route53 = MagicMock()
            route53.list_hosted_zones.return_value = {
                'HostedZones': [HOSTED_ZONE_ZO_NE],
                'IsTruncated': False,
                'MaxItems': '100'}
            return route53
        if rtype == 'acm':
            acm = MagicMock()
            summary_list = {'CertificateSummaryList': [
                {'CertificateArn': 'arn:aws:acm:eu-west-1:cert1'},
                {'CertificateArn': 'arn:aws:acm:eu-west-1:cert2'}]}
            acm.list_certificates.return_value = summary_list
            acm.describe_certificate.side_effect = [
                {'Certificate': CERT1_ZO_NE},
                {'Certificate': ''}]
            return acm
        return MagicMock()

    monkeypatch.setattr('boto3.client', my_client)
