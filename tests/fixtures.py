from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

CERT1_ZO_NE = {'CertificateArn': 'arn:aws:acm:eu-west-1:cert1',
               'CreatedAt': datetime(2016, 4, 1, 12, 13, 14, tzinfo=timezone.utc),
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
               'IssuedAt': datetime(2016, 4, 1, 12, 14, 14, tzinfo=timezone.utc),
               'Issuer': 'SenzaTest',
               'KeyAlgorithm': 'RSA-2048',
               'NotAfter': datetime(2017, 4, 1, 12, 14, 14, tzinfo=timezone.utc),
               'NotBefore': datetime(2016, 4, 1, 12, 14, 14, tzinfo=timezone.utc),
               'Serial': '00:00:00:00:00:00:00:00:00:00:00:00:00:00:00:00',
               'SignatureAlgorithm': 'SHA256WITHRSA',
               'Status': 'ISSUED',
               'Subject': 'CN=*.zo.ne',
               'SubjectAlternativeNames': []}

CERT1_ZO_NE_REVOKED = {'CertificateArn': 'arn:aws:acm:eu-west-1:cert1',
                       'CreatedAt': datetime(2016, 4, 1, 12, 13, 14, tzinfo=timezone.utc),
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
                       'IssuedAt': datetime(2016, 4, 1, 12, 14, 14, tzinfo=timezone.utc),
                       'Issuer': 'SenzaTest',
                       'KeyAlgorithm': 'RSA-2048',
                       'NotAfter': datetime(2017, 4, 1, 12, 14, 14, tzinfo=timezone.utc),
                       'NotBefore': datetime(2016, 4, 1, 12, 14, 14, tzinfo=timezone.utc),
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

SERVER_CERT_ZO_NE = MagicMock(name='zo-ne')
SERVER_CERT_ZO_NE.server_certificate_metadata = {'Arn': 'arn:aws:123',
                                                 'ServerCertificateName': 'zo-ne',
                                                 'Expiration': datetime(2017, 4, 1, 12, 14, 14,
                                                                        tzinfo=timezone(timedelta(hours=2))),
                                                 'Path': '/',
                                                 'ServerCertificateId': '000',
                                                 'UploadDate': datetime(2017, 3, 1, 12, 14, 14,
                                                                        tzinfo=timezone.utc)}


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
        elif rtype == 'acm':
            acm = MagicMock()
            summary_list = {'CertificateSummaryList': [
                {'CertificateArn': 'arn:aws:acm:eu-west-1:cert1'},
                {'CertificateArn': 'arn:aws:acm:eu-west-1:cert2'}]}
            acm.list_certificates.return_value = summary_list
            acm.describe_certificate.side_effect = [
                {'Certificate': CERT1_ZO_NE},
                {'Certificate': ''}]
            return acm
        elif rtype == 'cloudformation':
            cf = MagicMock()
            resource = {
                'StackResourceDetail': {'ResourceStatus': 'CREATE_COMPLETE',
                                        'ResourceType': 'AWS::IAM::Role',
                                        'PhysicalResourceId': 'my-referenced-role'}}
            cf.describe_stack_resource.return_value = resource
            return cf
        return MagicMock()

    monkeypatch.setattr('boto3.client', my_client)


@pytest.fixture
def boto_resource(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            ec2.security_groups.filter.return_value = [
                MagicMock(name='app-sg', id='sg-007')]
            ec2.vpcs.all.return_value = [MagicMock(vpc_id='vpc-123')]
            ec2.images.filter.return_value = [
                MagicMock(name='Taupage-AMI-123', id='ami-123')]
            ec2.subnets.filter.return_value = [MagicMock(tags=[{'Key': 'Name', 'Value': 'internal-myregion-1a'}],
                                                         id='subnet-abc123',
                                                         availability_zone='myregion-1a'),
                                               MagicMock(tags=[{'Key': 'Name',
                                                                'Value': 'internal-myregion-1b'}],
                                                         id='subnet-def456',
                                                         availability_zone='myregion-1b'),
                                               MagicMock(tags=[{'Key': 'Name',
                                                                'Value': 'dmz-myregion-1a'}],
                                                         id='subnet-ghi789',
                                                         availability_zone='myregion-1a')]
            return ec2
        elif rtype == 'iam':
            iam = MagicMock()
            iam.server_certificates.all.return_value = [SERVER_CERT_ZO_NE]
            return iam
        elif rtype == 'sns':
            sns = MagicMock()
            topic = MagicMock(arn='arn:123:mytopic')
            sns.topics.all.return_value = [topic]
            return sns
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)
