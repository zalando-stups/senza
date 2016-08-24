from datetime import datetime, timezone
from unittest.mock import MagicMock

from senza.manaus.acm import ACM, ACMCertificate, ACMCertificateStatus

CERT1 = {'CertificateArn': 'arn:aws:acm:eu-west-1:cert1',
         'CreatedAt': datetime(2016, 4, 1, 12, 13, 14, tzinfo=timezone.utc),
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
         'IssuedAt': datetime(2016, 4, 1, 12, 14, 14, tzinfo=timezone.utc),
         'Issuer': 'SenzaTest',
         'KeyAlgorithm': 'RSA-2048',
         'NotAfter': datetime(2017, 4, 1, 12, 14, 14, tzinfo=timezone.utc),
         'NotBefore': datetime(2016, 4, 1, 12, 14, 14, tzinfo=timezone.utc),
         'Serial': '00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00',
         'SignatureAlgorithm': 'SHA256WITHRSA',
         'Status': 'ISSUED',
         'Subject': 'CN=*.senza.example.com',
         'SubjectAlternativeNames': ['*.senza.example.com',
                                     '*.senza.aws.example.com',
                                     '*.app.example.com']}

CERT2 = {'CertificateArn': 'arn:aws:acm:eu-west-1:cert2',
         'CreatedAt': datetime(2016, 4, 1, 12, 13, 14),
         'DomainName': '*.senza.example.net',
         'DomainValidationOptions': [{'DomainName': '*.senza.example.net',
                                      'ValidationDomain': 'example.net',
                                      'ValidationEmails': [
                                          'hostmaster@example.net',
                                          'webmaster@example.net',
                                          'postmaster@example.net',
                                          'admin@example.net',
                                          'administrator@example.net']},
                                     {'DomainName': '*.bus.aws.example.net',
                                      'ValidationDomain': 'example.net',
                                      'ValidationEmails': [
                                          'hostmaster@example.net',
                                          'webmaster@example.net',
                                          'postmaster@example.net',
                                          'admin@example.net',
                                          'administrator@example.net']},
                                     {'DomainName': '*.app.example.net',
                                      'ValidationDomain': 'example.net',
                                      'ValidationEmails': [
                                          'hostmaster@example.net',
                                          'webmaster@example.net',
                                          'postmaster@example.net',
                                          'admin@example.net',
                                          'administrator@example.net']}],
         'InUseBy': ['arn:aws:elasticloadbalancing:eu-west-1:lb'],
         'IssuedAt': datetime(2016, 4, 1, 12, 14, 14),
         'Issuer': 'SenzaTest',
         'KeyAlgorithm': 'RSA-2048',
         'NotAfter': datetime(2017, 4, 1, 12, 14, 14),
         'NotBefore': datetime(2016, 4, 1, 12, 14, 14),
         'Serial': '00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00',
         'SignatureAlgorithm': 'SHA256WITHRSA',
         'Status': 'REVOKED',
         'Subject': 'CN=*.senza.example.net',
         'SubjectAlternativeNames': ['*.senza.example.net',
                                     '*.senza.aws.example.net',
                                     '*.app.example.net']}

CERT_VALIDATION_TIMED_OUT = {
    'KeyAlgorithm': 'RSA-2048',
    'DomainName': 'alpha.example.org',
    'InUseBy': [],
    'CreatedAt': datetime(2016, 7,  11, 15,  15,  30),
    'SubjectAlternativeNames': ['alpha.example.org'],
    'SignatureAlgorithm': 'SHA256WITHRSA',
    'Status': 'VALIDATION_TIMED_OUT',
    'DomainValidationOptions': [{'DomainName': 'alpha.example.org',
                                 'ValidationEmails': ['administrator@alpha.example.org',
                                    'hostmaster@alpha.example.org',
                                    'admin@alpha.example.org',
                                    'webmaster@alpha.example.org',
                                    'postmaster@alpha.example.org'],
                                 'ValidationDomain': 'alpha.example.org'}],
    'CertificateArn': 'arn:aws:acm:eu-central-1:123123:certificate/f8a0fa1a-381b-44b6-ab10-1b94ba1480a1',
    'Subject': 'CN=alpha.example.org'}


def test_certificate_valid():
    certificate1 = ACMCertificate.from_boto_dict(CERT1)
    assert certificate1.domain_name == '*.senza.example.com'
    assert certificate1.is_valid(when=datetime(2016, 4, 5, 12, 14, 14,
                                               tzinfo=timezone.utc))
    assert not certificate1.is_valid(when=datetime(2018, 4, 5, 12, 14, 14,
                                                   tzinfo=timezone.utc))
    assert not certificate1.is_valid(when=datetime(2013, 4, 2, 10, 11, 12,
                                                   tzinfo=timezone.utc))

    cert1_revoked = CERT1.copy()
    cert1_revoked['Status'] = 'REVOKED'

    certificate1_revoked = ACMCertificate.from_boto_dict(cert1_revoked)
    assert certificate1_revoked.domain_name == '*.senza.example.com'
    assert not certificate1_revoked.is_valid(when=datetime(2016, 4, 5, 12, 14, 14,
                                                           tzinfo=timezone.utc))
    assert not certificate1_revoked.is_valid(when=datetime(2018, 4, 5, 12, 14, 14,
                                                           tzinfo=timezone.utc))
    assert not certificate1_revoked.is_valid(when=datetime(2013, 4, 2, 10, 11, 12,
                                                           tzinfo=timezone.utc))

    cert_invalid = ACMCertificate.from_boto_dict(CERT_VALIDATION_TIMED_OUT)
    assert not cert_invalid.is_valid()


def test_certificate_comparison():
    cert2 = CERT1.copy()
    cert2['CreatedAt'] = datetime(2016, 4, 2, 12, 13, 14, tzinfo=timezone.utc)

    certificate1 = ACMCertificate.from_boto_dict(CERT1)
    certificate2 = ACMCertificate.from_boto_dict(cert2)

    assert certificate1 < certificate2
    # this may look weird but equality is tested by ARN
    assert certificate1 == certificate2


def test_certificate_get_by_arn(monkeypatch):
    m_client = MagicMock()
    m_client.return_value = m_client
    m_client.describe_certificate.return_value = {'Certificate': CERT1}
    monkeypatch.setattr('boto3.client', m_client)

    certificate1 = ACMCertificate.get_by_arn('dummy-region',
                                             'arn:aws:acm:eu-west-1:cert')
    assert certificate1.domain_name == '*.senza.example.com'
    assert certificate1.is_valid(when=datetime(2016, 4, 5, 12, 14, 14,
                                               tzinfo=timezone.utc))
    assert not certificate1.is_valid(when=datetime(2018, 4, 5, 12, 14, 14,
                                                   tzinfo=timezone.utc))
    assert not certificate1.is_valid(when=datetime(2013, 4, 2, 10, 11, 12,
                                                   tzinfo=timezone.utc))
    assert certificate1.status == ACMCertificateStatus.issued


def test_certificate_matches():
    certificate1 = ACMCertificate.from_boto_dict(CERT1)
    assert certificate1.matches('myapp.senza.example.com')
    assert certificate1.matches('myapp.app.example.com')
    assert certificate1.matches('myapp.senza.aws.example.com')
    assert not certificate1.matches('zalando.de')
    assert not certificate1.matches('sub.myapp.senza.aws.example.com')


def test_get_certificates(monkeypatch):
    m_client = MagicMock()
    m_client.return_value = m_client
    summary_list = {'CertificateSummaryList': [{'CertificateArn': 'arn:aws:acm:eu-west-1:cert1'},
                                               {'CertificateArn': 'arn:aws:acm:eu-west-1:cert2'}]}
    m_client.list_certificates.return_value = summary_list
    m_client.describe_certificate.side_effect = [{'Certificate': CERT1},
                                                 {'Certificate': CERT2}]
    monkeypatch.setattr('boto3.client', m_client)

    m_datetime = MagicMock()
    m_datetime.now.return_value = datetime(2016, 4, 5, 12, 14, 14,
                                           tzinfo=timezone.utc)
    monkeypatch.setattr('senza.manaus.acm.datetime', m_datetime)

    acm = ACM('dummy-region')
    certificates_default = list(acm.get_certificates())
    assert len(certificates_default) == 1  # Cert2 is excluded because it's REVOKED
    assert certificates_default[0].arn == 'arn:aws:acm:eu-west-1:cert1'

    m_client.describe_certificate.side_effect = [{'Certificate': CERT1},
                                                 {'Certificate': CERT2}]
    certificates_all = list(acm.get_certificates(valid_only=False))
    assert len(certificates_all) == 2

    m_client.describe_certificate.side_effect = [{'Certificate': CERT1},
                                                 {'Certificate': CERT2}]
    certificates_net = list(acm.get_certificates(valid_only=False,
                                                 domain_name="app.senza.example.net"))
    assert len(certificates_net) == 1
    assert certificates_net[0].arn == 'arn:aws:acm:eu-west-1:cert2'


def test_arn_is_acm_certificate():
    assert ACMCertificate.arn_is_acm_certificate('arn:aws:acm:certificate')
    assert not ACMCertificate.arn_is_acm_certificate('arn:aws:iam:certificate')
    assert not ACMCertificate.arn_is_acm_certificate(None)
