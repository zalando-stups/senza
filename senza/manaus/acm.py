from datetime import datetime
from enum import Enum
from typing import Iterator, List, Dict, Any, Optional
from functools import total_ordering

import boto3


class ACMCertificateStatus(str, Enum):
    expired = "EXPIRED"
    failed = "FAILED"
    inactive = "INACTIVE"
    issued = "ISSUED"
    pending_validation = "PENDING_VALIDATION"
    revoked = "REVOKED"
    validation_timed_out = "VALIDATION_TIMED_OUT"


@total_ordering
class ACMCertificate:
    """
    See:
    http://boto3.readthedocs.io/en/latest/reference/services/acm.html#ACM.Client.list_certificates
    http://boto3.readthedocs.io/en/latest/reference/services/acm.html#ACM.Client.describe_certificate
    """
    # TODO match method to find if a pattern or domain name match the certificate
    def __init__(self,
                 domain_name: str,
                 arn: str,
                 subject_alternative_name: List[str],
                 domain_validation_options: List[Dict],
                 serial: str,
                 subject: str,
                 issuer: str,
                 created_at: datetime,
                 issued_at: datetime,
                 status: ACMCertificateStatus,
                 not_before: datetime,
                 not_after: datetime,
                 signature_algorithm: str,
                 in_use_by: List[str],
                 revoked_at: Optional[datetime],
                 revocation_reason: Optional[str]):
        self.domain_name = domain_name
        self.arn = arn
        self.subject_alternative_name = subject_alternative_name
        self.domain_validation_options = domain_validation_options
        self.serial = serial
        self.subject = subject
        self.issuer = issuer
        self.created_at = created_at
        self.issued_at = issued_at
        self.status = status
        self.not_before = not_before
        self.not_after = not_after
        self.signature_algorithm = signature_algorithm
        self.in_use_by = in_use_by

        self.revoked_at = revoked_at
        self.revocation_reason = revocation_reason

    def __lt__(self, other: "ACMCertificate"):
        return self.created_at < other.created_at

    def __eq__(self, other: "ACMCertificate"):
        return self.arn == other.arn

    @classmethod
    def from_boto_dict(cls,
                       certificate: Dict[str, Any]) -> "ACMCertificate":
        """
        Creates an ACMCertificate based on the dictionary returned by
        describe_certificate
        """

        domain_name = certificate['DomainName']
        arn = certificate['CertificateArn']
        subject_alternative_name = certificate['SubjectAlternativeNames']
        domain_validation_options = certificate['DomainValidationOptions']
        serial = certificate['Serial']
        subject = certificate['Subject']
        issuer = certificate['Issuer']
        created_at = certificate['CreatedAt']
        issued_at = certificate['IssuedAt']
        status = ACMCertificateStatus(certificate['Status'].lower())
        not_before = certificate['NotBefore']
        not_after = certificate['NotAfter']
        signature_algorithm = certificate['SignatureAlgorithm']
        in_use_by = certificate['InUseBy']

        revoked_at = certificate.get('RevokedAt')
        revocation_reason = certificate.get('RevocationReason')

        return cls(domain_name, arn, subject_alternative_name,
                   domain_validation_options, serial, subject, issuer,
                   created_at, issued_at, status, not_before, not_after,
                   signature_algorithm, in_use_by,
                   revoked_at, revocation_reason)

    @classmethod
    def get_by_arn(cls, arn: str) -> "ACMCertificate":
        """
        Gets a ACMCertificate based on ARN alone
        """
        client = boto3.client('acm')
        certificate = client.describe_certificate(arn)['Certificate']
        return cls.from_boto_dict(certificate)

    def is_valid(self, when: Optional[datetime]=None) -> bool:
        """
        Checks if the certificate is still valid
        """
        if when is None:
            when = datetime.now()

        if self.status != ACMCertificateStatus.issued:
            return False

        return self.not_before < when < self.not_after


class ACM:
    """
    From https://aws.amazon.com/certificate-manager/

    AWS Certificate Manager is a service that lets you easily provision,
    manage, and deploy Secure Sockets Layer/Transport Layer Security (SSL/TLS)
    certificates for use with AWS services.

    See http://boto3.readthedocs.io/en/latest/reference/services/acm.html
    """

    def __init__(self):
        self.client = boto3.client('acm')

    def get_certificates(self) -> Iterator[ACMCertificate]:
        # TODO implement pagination
        # TODO limit status by default
        certificates = self.client.list_certificates()['CertificateSummaryList']
        for summary in certificates:
            arn = summary['CertificateArn']
            yield ACMCertificate.get_by_arn(arn)
