from datetime import datetime, timezone
from enum import Enum
from functools import total_ordering
from ssl import CertificateError, match_hostname
from typing import Any, Dict, Iterator, List, Optional

from .boto_proxy import BotoClientProxy


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
                 status: str,
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
        self.status = ACMCertificateStatus(status)
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

    def __repr__(self):
        return "<ACMCertificate:{domain_name} ({arn})>".format_map(vars(self))

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
        subject = certificate['Subject']
        created_at = certificate['CreatedAt']
        status = certificate['Status']
        signature_algorithm = certificate['SignatureAlgorithm']
        in_use_by = certificate['InUseBy']
        serial = certificate.get('Serial')
        issuer = certificate.get('Issuer')
        issued_at = certificate.get('IssuedAt')
        not_before = certificate.get('NotBefore')
        not_after = certificate.get('NotAfter')

        revoked_at = certificate.get('RevokedAt')
        revocation_reason = certificate.get('RevocationReason')

        return cls(domain_name, arn, subject_alternative_name,
                   domain_validation_options, serial, subject, issuer,
                   created_at, issued_at, status, not_before, not_after,
                   signature_algorithm, in_use_by,
                   revoked_at, revocation_reason)

    @classmethod
    def get_by_arn(cls, region: str, arn: str) -> "ACMCertificate":
        """
        Gets a ACMCertificate based on ARN alone
        """
        client = BotoClientProxy('acm', region)
        certificate = client.describe_certificate(CertificateArn=arn)['Certificate']
        return cls.from_boto_dict(certificate)

    @staticmethod
    def arn_is_acm_certificate(arn: Optional[str]=None) -> bool:
        if arn is None:
            return False
        else:
            return arn.startswith("arn:aws:acm:")

    def is_valid(self, when: Optional[datetime]=None) -> bool:
        """
        Checks if the certificate is still valid
        """
        when = when if when is not None else datetime.now(timezone.utc)

        if self.status != ACMCertificateStatus.issued:
            return False

        return self.not_before < when < self.not_after

    def matches(self, domain_name: str) -> bool:
        """
        Checks if certificate subject or alt names match the domain name.
        """
        # python ssl friendly certificate:
        subject = ((('commonName', self.domain_name),),)
        alt_name = [('DNS', name) for name in self.subject_alternative_name]
        certificate = {'subject': subject,
                       'subjectAltName': alt_name}

        try:
            match_hostname(certificate, domain_name)
        except CertificateError:
            return False
        else:
            return True


class ACM:
    """
    From https://aws.amazon.com/certificate-manager/

    AWS Certificate Manager is a service that lets you easily provision,
    manage, and deploy Secure Sockets Layer/Transport Layer Security (SSL/TLS)
    certificates for use with AWS services.

    See http://boto3.readthedocs.io/en/latest/reference/services/acm.html
    """

    def __init__(self, region=str):
        self.region = region

    def get_certificates(self,
                         *,
                         valid_only: bool=True,
                         domain_name: Optional[str]=None) -> Iterator[ACMCertificate]:
        """
        Gets certificates from ACM. By default it returns all valid certificates

        :param region: AWS region
        :param valid_only: Return only valid certificates
        :param domain_name: Return only certificates that match the domain
        """
        # TODO implement pagination
        client = BotoClientProxy('acm', self.region)
        certificates = client.list_certificates()['CertificateSummaryList']
        for summary in certificates:
            arn = summary['CertificateArn']
            certificate = ACMCertificate.get_by_arn(self.region, arn)
            if valid_only and not certificate.is_valid():
                pass
            elif domain_name is not None and not certificate.matches(domain_name):
                pass
            else:
                yield certificate
