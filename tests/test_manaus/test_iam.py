from datetime import datetime
from unittest.mock import MagicMock

from senza.manaus.iam import IAM, IAMServerCertificate

IAM_CERT1 = {'CertificateBody': 'body',
             'CertificateChain': 'chain',
             'ServerCertificateMetadata': {
                 'Arn': 'arn:aws:iam::0000:server-certificate/senza-example-com',
                 'Expiration': datetime(2022, 6, 29, 0, 0),
                 'Path': '/',
                 'ServerCertificateId': 'CERTIFICATEID',
                 'ServerCertificateName': 'senza-example-com',
                 'UploadDate': datetime(2015, 7, 1, 16, 0, 40)}}

IAM_CERT1_EXP = {'CertificateBody': 'body',
                 'CertificateChain': 'chain',
                 'ServerCertificateMetadata': {
                     'Arn': 'arn:aws:iam::0000:server-certificate/senza-example-com',
                     'Expiration': datetime(2015, 6, 29, 0, 0),
                     'Path': '/',
                     'ServerCertificateId': 'CERTIFICATEID',
                     'ServerCertificateName': 'senza-example-com',
                     'UploadDate': datetime(2015, 7, 1, 16, 0, 40)}}

IAM_CERT2 = {'CertificateBody': 'body',
             'CertificateChain': 'chain',
             'ServerCertificateMetadata': {
                 'Arn': 'arn:aws:iam::0000:server-certificate/senza-example-com',
                 'Expiration': datetime(2022, 6, 29, 0, 0),
                 'Path': '/',
                 'ServerCertificateId': 'CERTIFICATEID',
                 'ServerCertificateName': 'senza-example-com',
                 'UploadDate': datetime(2015, 7, 2, 16, 0, 40)}}


def test_certificate_from_name(monkeypatch):
    m_client = MagicMock()
    m_client.return_value = m_client
    m_client.get_server_certificate.return_value = {'ServerCertificate': IAM_CERT1}
    monkeypatch.setattr('boto3.client', m_client)

    certificate1 = IAMServerCertificate.get_by_name('senza-example-com')
    assert certificate1.name == 'senza-example-com'
    assert certificate1.arn == 'arn:aws:iam::0000:server-certificate/senza-example-com'


def test_from_boto_server_certificate(monkeypatch):
    mock_server_certificate = MagicMock()
    mock_server_certificate.certificate_body = 'certificate_body'
    mock_server_certificate.certificate_chain = 'certificate_chain'
    mock_server_certificate.server_certificate_metadata = {
                 'Arn': 'arn:aws:iam::0000:server-certificate/senza-example-com',
                 'Expiration': datetime(2022, 6, 29, 0, 0),
                 'Path': '/',
                 'ServerCertificateId': 'CERTIFICATEID',
                 'ServerCertificateName': 'senza-example-com',
                 'UploadDate': datetime(2015, 7, 2, 16, 0, 40)}
    certificate = IAMServerCertificate.from_boto_server_certificate(mock_server_certificate)

    assert certificate.arn == 'arn:aws:iam::0000:server-certificate/senza-example-com'
    assert certificate.name == 'senza-example-com'
    assert certificate.certificate_body == 'certificate_body'


def test_is_certificate_arn():
    assert IAMServerCertificate.arn_is_server_certificate('arn:aws:iam::0000:server-certificate/senza-example-com')
    assert not IAMServerCertificate.arn_is_server_certificate("arn:aws:iam:")
    assert not IAMServerCertificate.arn_is_server_certificate("server-certificate")
    assert not IAMServerCertificate.arn_is_server_certificate(None)

def test_order(monkeypatch):
    m_client = MagicMock()
    m_client.return_value = m_client
    monkeypatch.setattr('boto3.client', m_client)

    m_client.get_server_certificate.return_value = {'ServerCertificate': IAM_CERT1}
    certificate1 = IAMServerCertificate.get_by_name('senza-example-com')

    m_client.get_server_certificate.return_value = {'ServerCertificate': IAM_CERT2}
    certificate2 = IAMServerCertificate.get_by_name('senza-example-com')

    assert sorted([certificate1, certificate2]) == [certificate2, certificate1]
    assert sorted([certificate2, certificate1]) == [certificate2, certificate1]


def test_valid(monkeypatch):
    m_client = MagicMock()
    m_client.return_value = m_client
    m_client.get_server_certificate.return_value = {'ServerCertificate': IAM_CERT1}
    monkeypatch.setattr('boto3.client', m_client)

    certificate1 = IAMServerCertificate.get_by_name('senza-example-com')
    assert certificate1.is_valid(when=datetime(2016, 7, 1, 12, 12, 12))

    m_client.get_server_certificate.return_value = {'ServerCertificate': IAM_CERT1_EXP}
    certificate_expired = IAMServerCertificate.get_by_name('senza-example-com')
    assert not certificate_expired.is_valid(when=datetime(2016, 7, 1, 12, 12, 12))
