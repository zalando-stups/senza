"""
IAM related classes and functions.

For more information see the `IAM documentation`_ and the
`boto3 documentation`_

.. _IAM: http://docs.aws.amazon.com/IAM/latest/UserGuide/introduction.html
.. _IAM documentation: https://aws.amazon.com/documentation/iam/
.. _boto3 documentation:
    http://boto3.readthedocs.io/en/latest/reference/services/iam.html
"""

from datetime import datetime, timezone
from typing import Any, Dict, Iterator, Optional, Union

import boto3
from botocore.exceptions import ClientError

from .boto_proxy import BotoClientProxy


class IAMServerCertificate:
    """
    Server certificate stored in IAM.

    See:
    http://boto3.readthedocs.io/en/latest/reference/services/iam.html#IAM.Client.get_server_certificate
    """

    def __init__(self,
                 metadata: Dict[str, Union[str, datetime]],
                 certificate_body: str,
                 certificate_chain: str):

        self.metadata = metadata
        self.certificate_body = certificate_body
        self.certificate_chain = certificate_chain

        # metadata properties
        self.name = metadata['ServerCertificateName']  # type: str
        self.arn = metadata['Arn']  # type: str
        self.expiration = metadata['Expiration']  # type: datetime
        self.path = metadata['Path']  # type: str
        self.certificate_id = metadata['ServerCertificateId']  # type: str
        self.upload_date = metadata['UploadDate']  # type: datetime

    def __lt__(self, other: "IAMServerCertificate"):
        return self.upload_date < other.upload_date

    def __eq__(self, other: "IAMServerCertificate"):
        return self.arn == other.arn

    def __repr__(self):
        return "<IAMServerCertificate: {name}>".format_map(vars(self))

    @classmethod
    def from_boto_dict(cls,
                       server_certificate: Dict[str, Any]) -> "IAMServerCertificate":
        """
        Converts the dict returned by ``boto3.client.get_server_certificate``
        to a ``IAMServerCertificate`` instance.
        """

        metadata = server_certificate['ServerCertificateMetadata']
        certificate_body = server_certificate['CertificateBody']
        certificate_chain = server_certificate['CertificateChain']

        return cls(metadata, certificate_body, certificate_chain)

    @classmethod
    def from_boto_server_certificate(cls, server_certificate) -> "IAMServerCertificate":
        """
        Converts an ServerCertificate as returned by server_certificates.all()
        """
        metadata = server_certificate.server_certificate_metadata
        certificate_body = server_certificate.certificate_body
        certificate_chain = server_certificate.certificate_chain

        return cls(metadata, certificate_body, certificate_chain)

    @classmethod
    def get_by_name(cls, region: str, name: str) -> "IAMServerCertificate":
        """
        Get IAMServerCertificate using the name of the server certificate
        """
        client = BotoClientProxy('iam', region)
        iam = IAM(region)

        try:
            response = client.get_server_certificate(ServerCertificateName=name)
            server_certificate = response['ServerCertificate']
            certificate = cls.from_boto_dict(server_certificate)
        except ClientError as error:
            # IAM.get_certificates can get certificates with a suffix
            certificates = sorted(iam.get_certificates(name=name),
                                  reverse=True)
            try:
                # try to return the latest certificate that matches the name
                certificate = certificates[0]
            except IndexError:
                raise error

        return certificate

    @staticmethod
    def arn_is_server_certificate(arn: Optional[str]=None):
        """
        Checks if the Amazon Resource Name (ARN) refers to an iam
        server certificate.

        See:
        http://docs.aws.amazon.com/IAM/latest/UserGuide/reference_identifiers.html
        """
        if arn is None:
            return False
        else:
            return (arn.startswith("arn:aws:iam:") and
                    'server-certificate' in arn)

    def is_valid(self, when: Optional[datetime]=None) -> bool:
        """
        Checks if the certificate is still valid
        """
        when = when if when is not None else datetime.now(timezone.utc)

        return when < self.expiration


class IAM:

    """
    Represents the IAM service.

    See:
    http://boto3.readthedocs.io/en/latest/reference/services/iam.html
    """

    def __init__(self, region: str):
        self.region = region

    def get_certificates(self,
                         *,
                         valid_only: bool=True,
                         name: Optional[str]=None) -> Iterator[IAMServerCertificate]:
        """
        Gets certificates from IAM.
        By default it will fetch all valid certificates, but it's also possible
        to return also invalid certificates and filtering by name.
        """
        resource = boto3.resource('iam', self.region)

        for server_certificate in resource.server_certificates.all():
            certificate = IAMServerCertificate.from_boto_server_certificate(server_certificate)

            if name is not None and not certificate.name.startswith(name):
                continue

            if valid_only and not certificate.is_valid():
                continue

            yield certificate
