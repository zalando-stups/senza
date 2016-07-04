from datetime import datetime
from unittest.mock import MagicMock

from senza.manaus.acm import ACMCertificate

CERT1 = {'CertificateArn': 'arn:aws:acm:eu-west-1:cert',
         'CreatedAt': datetime(2016, 4, 1, 12, 13, 14),
         'DomainName': '*.senza.example.com',
         'DomainValidationOptions': [{'DomainName': '*.senza.example.com',
                                      'ValidationDomain': 'example.com',
                                      'ValidationEmails': [
                                          'hostmaster@example.com',
                                          'webmaster@example.com',
                                          'postmaster@example.com',
                                          'admin@example.com',
                                          'administrator@example.com']},
                                     {'DomainName': '*.bus.aws.example.com',
                                      'ValidationDomain': 'example.com',
                                      'ValidationEmails': [
                                          'hostmaster@example.com',
                                          'webmaster@example.com',
                                          'postmaster@example.com',
                                          'admin@example.com',
                                          'administrator@example.com']},
                                     {'DomainName': '*.app.example.com',
                                      'ValidationDomain': 'example.com',
                                      'ValidationEmails': [
                                          'hostmaster@example.com',
                                          'webmaster@example.com',
                                          'postmaster@example.com',
                                          'admin@example.com',
                                          'administrator@example.com']}],
         'InUseBy': ['arn:aws:elasticloadbalancing:eu-west-1:lb'],
         'IssuedAt': datetime(2016, 4, 1, 12, 14, 14),
         'Issuer': 'SenzaTest',
         'KeyAlgorithm': 'RSA-2048',
         'NotAfter': datetime(2017, 4, 1, 12, 14, 14),
         'NotBefore': datetime(2016, 4, 1, 12, 14, 14),
         'Serial': '00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00',
         'SignatureAlgorithm': 'SHA256WITHRSA',
         'Status': 'ISSUED',
         'Subject': 'CN=*.bus.example.com',
         'SubjectAlternativeNames': ['*.bus.example.com',
                                     '*.bus.aws.example.com',
                                     '*.app.example.com']}

CERT1_REVOKED = CERT1.copy()
CERT1_REVOKED['Status'] = 'REVOKED'


def test_certificate_valid():
    certificate1 = ACMCertificate.from_boto_dict(CERT1)
    assert certificate1.domain_name == '*.senza.example.com'
    assert certificate1.is_valid(when=datetime(2016, 4, 5, 12, 14, 14))
    assert not certificate1.is_valid(when=datetime(2018, 4, 5, 12, 14, 14))
    assert not certificate1.is_valid(when=datetime(2013, 4, 2, 10, 11, 12))

    certificate1_revoked = ACMCertificate.from_boto_dict(CERT1_REVOKED)
    assert certificate1_revoked.domain_name == '*.senza.example.com'
    assert not certificate1_revoked.is_valid(when=datetime(2016, 4, 5, 12, 14, 14))
    assert not certificate1_revoked.is_valid(when=datetime(2018, 4, 5, 12, 14, 14))
    assert not certificate1_revoked.is_valid(when=datetime(2013, 4, 2, 10, 11, 12))
