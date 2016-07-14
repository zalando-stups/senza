from datetime import datetime, timezone
from unittest.mock import MagicMock
import pytest

from botocore.exceptions import ClientError
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
                     'Arn': 'arn:aws:iam::0000:server-certificate/senza-example-com-20150701',
                     'Expiration': datetime(2015, 6, 29, 0, 0),
                     'Path': '/',
                     'ServerCertificateId': 'CERTIFICATEID',
                     'ServerCertificateName': 'senza-example-com-20150701',
                     'UploadDate': datetime(2015, 7, 1, 16, 0, 40)}}

IAM_CERT2 = {'CertificateBody': 'body',
             'CertificateChain': 'chain',
             'ServerCertificateMetadata': {
                 'Arn': 'arn:aws:iam::0001:server-certificate/senza-example-com-20150702',
                 'Expiration': datetime(2022, 6, 29, 0, 0),
                 'Path': '/',
                 'ServerCertificateId': 'CERTIFICATEID',
                 'ServerCertificateName': 'senza-example-com-20150702',
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
    mock_cert = MagicMock()
    mock_cert.certificate_body = 'certificate_body'
    mock_cert.certificate_chain = 'certificate_chain'
    mock_cert.server_certificate_metadata = {'Arn': 'arn:aws:iam::0000:server-certificate/senza-example-com',
                                             'Expiration': datetime(2022, 6, 29, 0, 0),
                                             'Path': '/',
                                             'ServerCertificateId': 'CERTIFICATEID',
                                             'ServerCertificateName': 'senza-example-com',
                                             'UploadDate': datetime(2015, 7, 2, 16, 0, 40)}
    certificate = IAMServerCertificate.from_boto_server_certificate(mock_cert)

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

    assert certificate2 > certificate1
    assert sorted([certificate1, certificate2]) == [certificate1, certificate2]
    assert sorted([certificate2, certificate1]) == [certificate1, certificate2]


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


def test_get_certificates(monkeypatch):
    mock_certificate1 = MagicMock()
    mock_certificate1.certificate_body = 'certificate_body'
    mock_certificate1.certificate_chain = 'certificate_chain'
    mock_certificate1.server_certificate_metadata = {
        'Arn': 'arn:aws:iam::0000:server-certificate/senza-example-com',
        'Expiration': datetime(2022, 6, 29, 0, 0, tzinfo=timezone.utc),
        'Path': '/',
        'ServerCertificateId': 'CERTIFICATEID',
        'ServerCertificateName': 'senza-example-com',
        'UploadDate': datetime(2015, 7, 2, 16, 0, 40, tzinfo=timezone.utc)}

    mock_certificate2 = MagicMock()
    mock_certificate2.certificate_body = 'certificate_body'
    mock_certificate2.certificate_chain = 'certificate_chain'
    mock_certificate2.server_certificate_metadata = {
        'Arn': 'arn:aws:iam::0000:server-certificate/senza-example-net',
        'Expiration': datetime(2022, 6, 29, 0, 0, tzinfo=timezone.utc),
        'Path': '/',
        'ServerCertificateId': 'CERTIFICATEID',
        'ServerCertificateName': 'senza-example-net',
        'UploadDate': datetime(2015, 7, 2, 16, 0, 40, tzinfo=timezone.utc)}

    mock_certificate3 = MagicMock()
    mock_certificate3.certificate_body = 'certificate_body'
    mock_certificate3.certificate_chain = 'certificate_chain'
    mock_certificate3.server_certificate_metadata = {
        'Arn': 'arn:aws:iam::0000:server-certificate/senza-example-org',
        'Expiration': datetime(2015, 6, 1, 0, 0, tzinfo=timezone.utc),
        'Path': '/',
        'ServerCertificateId': 'CERTIFICATEID',
        'ServerCertificateName': 'senza-example-org',
        'UploadDate': datetime(2015, 7, 2, 16, 0, 40, tzinfo=timezone.utc)}

    m_resource = MagicMock()
    m_resource.return_value = m_resource
    m_resource.server_certificates.all.return_value = [mock_certificate1,
                                                       mock_certificate2,
                                                       mock_certificate3]
    monkeypatch.setattr('boto3.resource', m_resource)

    m_datetime = MagicMock()
    m_datetime.now.return_value = datetime(2016, 4, 5, 12, 14, 14,
                                           tzinfo=timezone.utc)
    monkeypatch.setattr('senza.manaus.iam.datetime', m_datetime)

    certificates = list(IAM.get_certificates())
    for certificate in certificates:
        assert certificate.is_valid()
    assert len(certificates) == 2

    all_certificates = list(IAM.get_certificates(valid_only=False))
    assert len(all_certificates) == 3

    certificates_net = list(IAM.get_certificates(name='senza-example-net'))
    assert len(certificates_net) == 1
    assert certificates_net[0].name == 'senza-example-net'

    certificates_org = list(IAM.get_certificates(name='senza-example-org'))
    assert len(certificates_org) == 0


def test_get_with_suffix(monkeypatch):
    mock_certificate1 = MagicMock()
    mock_certificate1.certificate_body = 'certificate_body'
    mock_certificate1.certificate_chain = 'certificate_chain'
    mock_certificate1.server_certificate_metadata = {
        'Arn': 'arn:aws:iam::0000:server-certificate/senza-example-com',
        'Expiration': datetime(2022, 6, 29, 0, 0, tzinfo=timezone.utc),
        'Path': '/',
        'ServerCertificateId': 'CERTIFICATEID',
        'ServerCertificateName': 'senza-example-com',
        'UploadDate': datetime(2015, 7, 2, 16, 0, 40, tzinfo=timezone.utc)}

    mock_certificate2 = MagicMock()
    mock_certificate2.certificate_body = 'certificate_body'
    mock_certificate2.certificate_chain = 'certificate_chain'
    mock_certificate2.server_certificate_metadata = {
        'Arn': 'arn:aws:iam::0000:server-certificate/senza-example-net',
        'Expiration': datetime(2022, 6, 29, 0, 0, tzinfo=timezone.utc),
        'Path': '/',
        'ServerCertificateId': 'CERTIFICATEID',
        'ServerCertificateName': 'senza-example-net',
        'UploadDate': datetime(2015, 7, 2, 16, 0, 40, tzinfo=timezone.utc)}

    mock_certificate3 = MagicMock()
    mock_certificate3.certificate_body = 'certificate_body'
    mock_certificate3.certificate_chain = 'certificate_chain'
    mock_certificate3.server_certificate_metadata = {
        'Arn': 'arn:aws:iam::0000:server-certificate/senza-example-org',
        'Expiration': datetime(2015, 6, 1, 0, 0, tzinfo=timezone.utc),
        'Path': '/',
        'ServerCertificateId': 'CERTIFICATEID',
        'ServerCertificateName': 'senza-example-org-20150702',
        'UploadDate': datetime(2015, 7, 2, 16, 0, 40, tzinfo=timezone.utc)}

    mock_certificate4 = MagicMock()
    mock_certificate4.certificate_body = 'certificate_body'
    mock_certificate4.certificate_chain = 'certificate_chain'
    mock_certificate4.server_certificate_metadata = {
        'Arn': 'arn:aws:iam::0001:server-certificate/senza-example-org',
        'Expiration': datetime(2015, 6, 1, 0, 0, tzinfo=timezone.utc),
        'Path': '/',
        'ServerCertificateId': 'CERTIFICATEID',
        'ServerCertificateName': 'senza-example-org-20150703',
        'UploadDate': datetime(2015, 7, 3, 16, 0, 40, tzinfo=timezone.utc)}

    m_resource = MagicMock()
    m_resource.return_value = m_resource
    m_resource.server_certificates.all.return_value = [mock_certificate1,
                                                       mock_certificate4,
                                                       mock_certificate2,
                                                       mock_certificate3]
    monkeypatch.setattr('boto3.resource', m_resource)

    m_client = MagicMock()
    m_client.return_value = m_client
    error = {'Error': {'Type': 'Sender',
                       'Message': 'The Server Certificate with name hello'
                                  ' cannot be found.',
                       'Code': 'NoSuchEntity'}}
    m_client.get_server_certificate.side_effect = ClientError(error,
                                                              'test')
    monkeypatch.setattr('boto3.client', m_client)

    m_datetime = MagicMock()
    m_datetime.now.return_value = datetime(2014, 4, 5, 12, 14, 14,
                                           tzinfo=timezone.utc)
    monkeypatch.setattr('senza.manaus.iam.datetime', m_datetime)

    certificate1 = IAMServerCertificate.get_by_name('senza-example-org')
    assert certificate1.name == 'senza-example-org-20150703'

    with pytest.raises(ClientError):
        m_resource.server_certificates.all.return_value = []
        IAMServerCertificate.get_by_name('senza-example-org')
