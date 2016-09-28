from collections import defaultdict
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
    mocks = defaultdict(lambda: MagicMock())

    mocks['cloudformation'] = MagicMock()
    mocks['cloudformation'].list_stacks.return_value = {'StackSummaries': [
        {'StackName': 'test-1',
         'StackId': 'arn:aws:cf:eu-1:test',
         'CreationTime': '2016-06-14'}]
    }
    summary = [{'LastUpdatedTimestamp': datetime(2016, 7, 20, 7, 3, 7,
                                                 108000,
                                                 tzinfo=timezone.utc),
                'LogicalResourceId': 'AppLoadBalancer',
                'PhysicalResourceId': 'myapp1-1',
                'ResourceStatus': 'CREATE_COMPLETE',
                'ResourceType': 'AWS::ElasticLoadBalancing::LoadBalancer'},
               {'LastUpdatedTimestamp': datetime(2016, 7, 20, 7, 3,
                                                 45, 70000,
                                                 tzinfo=timezone.utc),
                'LogicalResourceId': 'AppLoadBalancerMainDomain',
                'PhysicalResourceId': 'myapp1.example.com',
                'ResourceStatus': 'CREATE_COMPLETE',
                'ResourceType': 'AWS::Route53::RecordSet'},
               {'LastUpdatedTimestamp': datetime(2016, 7, 20, 7, 3,
                                                 43, 871000,
                                                 tzinfo=timezone.utc),
                'LogicalResourceId': 'AppLoadBalancerVersionDomain',
                'PhysicalResourceId': 'myapp1-1.example.com',
                'ResourceStatus': 'CREATE_COMPLETE',
                'ResourceType': 'AWS::Route53::RecordSet'},
               {'LastUpdatedTimestamp': datetime(2016, 7, 20, 7, 7,
                                                 38, 495000,
                                                 tzinfo=timezone.utc),
                'LogicalResourceId': 'AppServer',
                'PhysicalResourceId': 'myapp1-1-AppServer-00000',
                'ResourceStatus': 'CREATE_COMPLETE',
                'ResourceType': 'AWS::AutoScaling::AutoScalingGroup'},
               {'LastUpdatedTimestamp': datetime(2016, 7, 20, 7, 5,
                                                 10, 48000,
                                                 tzinfo=timezone.utc),
                'LogicalResourceId': 'AppServerConfig',
                'PhysicalResourceId': 'myapp1-1-AppServerConfig-00000',
                'ResourceStatus': 'CREATE_COMPLETE',
                'ResourceType': 'AWS::AutoScaling::LaunchConfiguration'},
               {'LastUpdatedTimestamp': datetime(2016, 7, 20, 7, 5, 6,
                                                 745000,
                                                 tzinfo=timezone.utc),
                'LogicalResourceId': 'AppServerInstanceProfile',
                'PhysicalResourceId': 'myapp1-1-AppServerInstanceProfile-000',
                'ResourceStatus': 'CREATE_COMPLETE',
                'ResourceType': 'AWS::IAM::InstanceProfile'}]


    response = {'ResponseMetadata': {'HTTPStatusCode': 200,
                                     'RequestId': '0000'},
                'StackResourceSummaries': summary}
    mocks['cloudformation'].list_stack_resources.return_value = response

    mocks['route53'] = MagicMock()
    mocks['route53'].list_hosted_zones.return_value = {
        'HostedZones': [HOSTED_ZONE_ZO_NE],
        'IsTruncated': False,
        'MaxItems': '100'}
    mocks['route53'].list_resource_record_sets.return_value = {
        'IsTruncated': False,
        'MaxItems': '100',
        'ResourceRecordSets': [
            {'Name': 'example.org.',
             'ResourceRecords': [{'Value': 'ns.awsdns.com.'},
                                 {'Value': 'ns.awsdns.org.'}],
             'TTL': 172800,
             'Type': 'NS'},
            {'Name': 'test-1.example.org.',
             'ResourceRecords': [
                 {'Value': 'test-1-123.myregion.elb.amazonaws.com'}],
             'TTL': 20,
             'Type': 'CNAME'},
            {'Name': 'mydomain.example.org.',
             'ResourceRecords': [{'Value': 'test-1.example.org'}],
             'SetIdentifier': 'test-1',
             'TTL': 20,
             'Type': 'CNAME',
             'Weight': 20},
            {'Name': 'test-2.example.org.',
             'AliasTarget': {'DNSName': 'test-2-123.myregion.elb.amazonaws.com'},
             'TTL': 20,
             'Type': 'A'},
        ]}

    def my_client(rtype, *args, **kwargs):
        if rtype == 'acm':
            acm = mocks['acm']
            summary_list = {'CertificateSummaryList': [
                {'CertificateArn': 'arn:aws:acm:eu-west-1:cert1'},
                {'CertificateArn': 'arn:aws:acm:eu-west-1:cert2'}]}
            mocks['acm'].list_certificates.return_value = summary_list
            acm.describe_certificate.side_effect = [
                {'Certificate': CERT1_ZO_NE},
                {'Certificate': ''}]
            return acm
        elif rtype == 'cloudformation':
            cf = mocks['cloudformation']
            resource = {
                'StackResourceDetail': {'ResourceStatus': 'CREATE_COMPLETE',
                                        'ResourceType': 'AWS::IAM::Role',
                                        'PhysicalResourceId': 'my-referenced-role'}}
            cf.describe_stack_resource.return_value = resource
            cf.describe_stacks.return_value = {
                'Stacks': [{
                    'Parameters': [],
                    'Tags': [],
                    'StackName': 'test-1',
                    'CreationTime': datetime(2016, 8, 31, 6, 16, 37, 917000,
                                             tzinfo=timezone.utc),
                    'DisableRollback': False,
                    'Description': 'Test1',
                    'StackStatus': 'CREATE_COMPLETE',
                    'NotificationARNs': [],
                    'StackId': 'arn:aws:cloudformation:eu-central-1:test'}
                ],
                'ResponseMetadata': {},
                'RequestId': 'test'
            }

            return cf
        return mocks[rtype]

    monkeypatch.setattr('boto3.client', my_client)
    return mocks


@pytest.fixture
def boto_resource(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'cloudformation':
            res = MagicMock()
            res.resource_type = 'AWS::Route53::RecordSet'
            res.physical_resource_id = 'test-1.example.org'
            res.logical_id = 'VersionDomain'
            res.last_updated_timestamp = datetime.now()
            res2 = MagicMock()
            res2.resource_type = 'AWS::Route53::RecordSet'
            res2.physical_resource_id = 'mydomain.example.org'
            res2.logical_id = 'MainDomain'
            res2.last_updated_timestamp = datetime.now()
            res3 = MagicMock()
            res3.resource_type = 'AWS::Route53::RecordSet'
            res3.physical_resource_id = 'test-2.example.org'
            res3.logical_id = 'VersionDomain'
            res3.last_updated_timestamp = datetime.now()
            stack = MagicMock()
            stack.resource_summaries.all.return_value = [res, res2, res3]
            cf = MagicMock()
            cf.Stack.return_value = stack
            return cf
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


@pytest.fixture(autouse=True)
def valid_regions(monkeypatch):
    m_session = MagicMock()
    m_session.return_value = m_session
    m_session.get_available_regions.return_value = ['aa-fakeregion-1']
    monkeypatch.setattr('boto3.session.Session', m_session)
    return m_session
