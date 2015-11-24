import datetime
import os
from click.testing import CliRunner
import collections
from unittest.mock import MagicMock
import yaml
import json
from senza.cli import cli, handle_exceptions, AccountArguments
import botocore.exceptions
from senza.traffic import PERCENT_RESOLUTION, StackVersion
import senza.traffic


def test_invalid_definition():
    data = {}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123'], catch_exceptions=False)

    assert 'Error: Invalid value for "definition"' in result.output


def test_file_not_found():
    data = {}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'notfound.yaml', '--region=myregion', '123'], catch_exceptions=False)

    assert '"notfound.yaml" not found' in result.output


def test_version():
    runner = CliRunner()
    result = runner.invoke(cli, ['--version'])
    assert result.output.startswith('Senza ')


def test_missing_credentials(capsys):
    func = MagicMock(side_effect=botocore.exceptions.NoCredentialsError())

    try:
        handle_exceptions(func)()
    except SystemExit:
        pass

    out, err = capsys.readouterr()
    assert 'No AWS credentials found.' in err


def test_expired_credentials(capsys):
    func = MagicMock(side_effect=botocore.exceptions.ClientError({'Error': {'Code': 'ExpiredToken',
                                                                            'Message': 'Token expired'}},
                                                                 'foobar'))

    try:
        handle_exceptions(func)()
    except SystemExit:
        pass

    out, err = capsys.readouterr()

    assert 'AWS credentials have expired.' in err


def test_print_minimal(monkeypatch):
    monkeypatch.setattr('boto3.client', lambda *args: MagicMock())

    data = {'SenzaInfo': {'StackName': 'test'}, 'Resources': {'MyQueue': {'Type': 'AWS::SQS::Queue'}}}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123'],
                               catch_exceptions=False)

    assert 'AWSTemplateFormatVersion' in result.output


def test_print_basic(monkeypatch):
    monkeypatch.setattr('boto3.client', lambda *args: MagicMock())

    data = {'SenzaInfo': {'StackName': 'test'}, 'SenzaComponents': [{'Configuration': {'Type': 'Senza::Configuration',
                                                                                       'ServerSubnets': {
                                                                                           'myregion': [
                                                                                               'subnet-123']}}},
                                                                    {'AppServer': {
                                                                        'Type': 'Senza::TaupageAutoScalingGroup',
                                                                        'InstanceType': 't2.micro',
                                                                        'Image': 'AppImage',
                                                                        'TaupageConfig': {'runtime': 'Docker',
                                                                                          'source': 'foo/bar'}}}]}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123'],
                               catch_exceptions=False)

    assert 'AWSTemplateFormatVersion' in result.output
    assert 'subnet-123' in result.output


def test_print_replace_mustache(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            ec2.security_groups.filter.return_value = [MagicMock(name='app-master-mind', id='sg-007')]
            return ec2
        return MagicMock()

    monkeypatch.setattr('boto3.client', MagicMock())
    monkeypatch.setattr('boto3.resource', my_resource)
    data = {'SenzaInfo': {'StackName': 'test',
                          'Parameters': [{'ApplicationId': {'Description': 'Application ID from kio'}}]},
            'SenzaComponents': [{'Configuration': {'ServerSubnets': {'myregion': ['subnet-123']},
                                                   'Type': 'Senza::Configuration'}},
                                {'AppServer': {'Image': 'AppImage',
                                               'InstanceType': 't2.micro',
                                               'SecurityGroups': ['app-{{Arguments.ApplicationId}}'],
                                               'IamRoles': ['app-{{Arguments.ApplicationId}}'],
                                               'TaupageConfig': {'runtime': 'Docker',
                                                                 'source': 'foo/bar'},
                                               'Type': 'Senza::TaupageAutoScalingGroup'}}]
            }

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123', 'master-mind'],
                               catch_exceptions=False)
    assert 'AWSTemplateFormatVersion' in result.output
    assert 'subnet-123' in result.output
    assert 'app-master-mind' in result.output
    assert 'sg-007' in result.output


def test_print_account_info(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            ec2.security_groups.filter.return_value = [MagicMock(name='app-master-mind', id='sg-007')]
            return ec2
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)

    boto3 = MagicMock()
    boto3.get_user.return_value = {'User': {'Arn': 'arn:aws:iam::0123456789:user/admin'}}
    boto3.list_account_aliases.return_value = {'AccountAliases': ['org-dummy']}

    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    data = {'SenzaComponents': [{'Configuration': {'ServerSubnets': {'myregion': ['subnet-123']},
                                                   'Type': 'Senza::Configuration'}},
                                {'AppServer': {'Image': 'AppImage-{{AccountInfo.TeamID}}-{{AccountInfo.AccountID}}',
                                               'InstanceType': 't2.micro',
                                               'TaupageConfig': {'runtime': 'Docker',
                                                                 'source': 'foo/bar'},
                                               'Type': 'Senza::TaupageAutoScalingGroup'}}],
            'SenzaInfo': {'StackName': 'test-{{AccountInfo.Region}}'}}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123'],
                               catch_exceptions=False)
    assert '"StackName": "test-myregion",' in result.output
    assert 'AppImage-dummy-0123456789' in result.output


def test_print_account_info_and_arguments_in_name(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            ec2.security_groups.filter.return_value = [MagicMock(name='app-master-mind', id='sg-007')]
            return ec2
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)

    boto3 = MagicMock()
    boto3.get_user.return_value = {'User': {'Arn': 'arn:aws:iam::0123456789:user/admin'}}
    boto3.list_account_aliases.return_value = {'AccountAliases': ['org-dummy']}

    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    data = {'SenzaComponents': [{'Configuration': {'ServerSubnets': {'myregion': ['subnet-123']},
                                                   'Type': 'Senza::Configuration'}},
                                {'AppServer': {'Image': 'AppImage-{{AccountInfo.TeamID}}-{{AccountInfo.AccountID}}',
                                               'InstanceType': 't2.micro',
                                               'TaupageConfig': {'runtime': 'Docker',
                                                                 'source': 'foo/bar'},
                                               'Type': 'Senza::TaupageAutoScalingGroup'}}],
            'SenzaInfo': {'StackName': 'test-{{AccountInfo.Region}}-{{Arguments.Section}}',
                          'Parameters': [{'Section': {'Description': 'Section for A/B Test'}}]}}
    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123', 'B'],
                               catch_exceptions=False)
    assert '"StackName": "test-myregion-B",' in result.output
    assert 'AppImage-dummy-0123456789' in result.output


def test_print_auto(monkeypatch):
    senza.traffic.DNS_ZONE_CACHE = {}

    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            ec2.security_groups.filter.return_value = [MagicMock(name='app-sg', id='sg-007')]
            ec2.vpcs.all.return_value = [MagicMock(vpc_id='vpc-123')]
            ec2.images.filter.return_value = [MagicMock(name='Taupage-AMI-123', id='ami-123')]
            ec2.subnets.filter.return_value = [MagicMock(tags=[{'Key': 'Name', 'Value': 'internal-myregion-1a'}],
                                                         id='subnet-abc123',
                                                         availability_zone='myregion-1a'),
                                               MagicMock(tags=[{'Key': 'Name', 'Value': 'internal-myregion-1b'}],
                                                         id='subnet-def456',
                                                         availability_zone='myregion-1b'),
                                               MagicMock(tags=[{'Key': 'Name', 'Value': 'dmz-myregion-1a'}],
                                                         id='subnet-ghi789',
                                                         availability_zone='myregion-1a')
                                               ]
            return ec2
        elif rtype == 'iam':
            iam = MagicMock()
            iam.server_certificates.all.return_value = [MagicMock(name='zo-ne',
                                                                  server_certificate_metadata={'Arn': 'arn:aws:123'})]
            return iam
        elif rtype == 'sns':
            sns = MagicMock()
            topic = MagicMock(arn='arn:123:mytopic')
            sns.topics.all.return_value = [topic]
            return sns
        return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'route53':
            route53 = MagicMock()
            route53.list_hosted_zones.return_value = {'HostedZones': [{'Id': '/hostedzone/123456',
                                                                       'Name': 'zo.ne.',
                                                                       'ResourceRecordSetCount': 23}],
                                                      'IsTruncated': False,
                                                      'MaxItems': '100'}
            return route53
        return MagicMock()

    monkeypatch.setattr('boto3.client', my_client)
    monkeypatch.setattr('boto3.resource', my_resource)

    data = {'SenzaInfo': {'StackName': 'test',
                          'OperatorTopicId': 'mytopic',
                          'Parameters': [{'ImageVersion': {'Description': ''}}]},
            'SenzaComponents': [{'Configuration': {'Type': 'Senza::StupsAutoConfiguration'}},
                                {'AppServer': {'Type': 'Senza::TaupageAutoScalingGroup',
                                               'ElasticLoadBalancer': 'AppLoadBalancer',
                                               'InstanceType': 't2.micro',
                                               'TaupageConfig': {'runtime': 'Docker',
                                                                 'source': 'foo/bar:{{Arguments.ImageVersion}}'},
                                               'IamRoles': ['app-myrole'],
                                               'SecurityGroups': ['app-sg', 'sg-123'],
                                               'AutoScaling':
                                                   {'Minimum': 1,
                                                    'Maximum': 10,
                                                    'MetricType': 'CPU'}}},
                                {'AppLoadBalancer': {'Type': 'Senza::WeightedDnsElasticLoadBalancer',
                                                     'HTTPPort': 8080,
                                                     'SecurityGroups': ['app-sg']}}]}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123', '1.0-SNAPSHOT'],
                               catch_exceptions=False)
    # no stdout/stderr seperation with runner.invoke...
    stdout, cfjson = result.output.split('\n', 1)
    assert 'Generating Cloud Formation template.. OK' == stdout
    data = json.loads(cfjson)
    assert 'AWSTemplateFormatVersion' in data.keys()
    assert 'subnet-abc123' in data['Mappings']['ServerSubnets']['myregion']['Subnets']
    assert 'subnet-ghi789' not in data['Mappings']['ServerSubnets']['myregion']['Subnets']
    assert 'subnet-ghi789' in data['Mappings']['LoadBalancerSubnets']['myregion']['Subnets']
    assert 'source: foo/bar:1.0-SNAPSHO' in data['Resources']['AppServerConfig']['Properties']['UserData']['Fn::Base64']
    assert 'ELB' == data['Resources']['AppServer']['Properties']['HealthCheckType']


def test_print_default_value(monkeypatch):
    senza.traffic.DNS_ZONE_CACHE = {}

    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            ec2.vpcs.all.return_value = [MagicMock(vpc_id='vpc-123')]
            ec2.security_groups.filter.return_value = [MagicMock(name='app-sg', id='sg-007')]
            ec2.images.filter.return_value = [MagicMock(name='Taupage-AMI-123', id='ami-123')]
            return ec2
        elif rtype == 'iam':
            iam = MagicMock()
            iam.server_certificates.all.return_value = [MagicMock(name='zo-ne',
                                                                  server_certificate_metadata={'Arn': 'arn:aws:123'})]
            return iam
        elif rtype == 'sns':
            sns = MagicMock()
            topic = MagicMock(arn='arn:123:mytopic')
            sns.topics.all.return_value = [topic]
            return sns
        return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'route53':
            route53 = MagicMock()
            route53.list_hosted_zones.return_value = {'HostedZones': [{'Id': '/hostedzone/123456',
                                                                       'Name': 'zo.ne.',
                                                                       'ResourceRecordSetCount': 23}],
                                                      'IsTruncated': False,
                                                      'MaxItems': '100'}
            return route53
        return MagicMock()

    monkeypatch.setattr('boto3.client', my_client)
    monkeypatch.setattr('boto3.resource', my_resource)

    data = {'SenzaInfo': {'StackName': 'test',
                          'OperatorTopicId': 'mytopic',
                          'Parameters': [{'ImageVersion': {'Description': ''}},
                                         {'ExtraParam': {'Type': 'String'}},
                                         {'DefParam': {'Default': 'DefValue',
                                                       'Type': 'String'}}]},
            'SenzaComponents': [{'Configuration': {'Type': 'Senza::StupsAutoConfiguration'}},
                                {'AppServer': {'Type': 'Senza::TaupageAutoScalingGroup',
                                               'ElasticLoadBalancer': 'AppLoadBalancer',
                                               'InstanceType': 't2.micro',
                                               'TaupageConfig': {'runtime': 'Docker',
                                                                 'source': 'foo/bar:{{Arguments.ImageVersion}}',
                                                                 'DefParam': '{{Arguments.DefParam}}',
                                                                 'ExtraParam': '{{Arguments.ExtraParam}}'}}},
                                {'AppLoadBalancer': {'Type': 'Senza::WeightedDnsElasticLoadBalancer',
                                                     'HTTPPort': 8080,
                                                     'SecurityGroups': ['app-sg']}}]}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123', '1.0-SNAPSHOT', 'extra value'],
                               catch_exceptions=False)
        assert 'DefParam: DefValue\\n' in result.output
        assert 'ExtraParam: extra value\\n' in result.output

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123', '1.0-SNAPSHOT', 'extra value',
                                     'other def value'],
                               catch_exceptions=False)
        assert 'DefParam: other def value\\n' in result.output
        assert 'ExtraParam: extra value\\n' in result.output


def test_print_taupage_config_without_ref(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            ec2.security_groups.filter.return_value = [MagicMock(name='app-master-mind', id='sg-007')]
            return ec2
        return MagicMock()

    monkeypatch.setattr('boto3.client', MagicMock())
    monkeypatch.setattr('boto3.resource', my_resource)
    data = {'SenzaInfo': {'StackName': 'test',
                          'Parameters': [{'ApplicationId': {'Description': 'Application ID from kio'}}]},
            'SenzaComponents': [{'Configuration': {'ServerSubnets': {'myregion': ['subnet-123']},
                                                   'Type': 'Senza::Configuration'}},
                                {'AppServer': {'Image': 'AppImage',
                                               'InstanceType': 't2.micro',
                                               'SecurityGroups': ['app-{{Arguments.ApplicationId}}'],
                                               'IamRoles': ['app-{{Arguments.ApplicationId}}'],
                                               'TaupageConfig': {'runtime': 'Docker',
                                                                 'source': 'foo/bar',
                                                                 'ports': {80: 80},
                                                                 'mint_bucket': 'zalando-mint-bucket',
                                                                 'environment': {'ENV1': 'v1',
                                                                                 'ENV2': 'v2'}},
                                               'Type': 'Senza::TaupageAutoScalingGroup'}}]
            }

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd, default_flow_style=False)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123', 'master-mind'],
                               catch_exceptions=False)

    stdout, cfjson = result.output.split('\n', 1)
    assert 'Generating Cloud Formation template.. OK' == stdout
    awsjson = json.loads(cfjson)

    expected_user_data = "#taupage-ami-config\napplication_id: test\napplication_version: '123'\n" \
                         "environment:\n  ENV1: v1\n  ENV2: v2\nmint_bucket: zalando-mint-bucket\n" \
                         "notify_cfn:\n  resource: AppServer\n  stack: test-123\nports:\n  80: 80\n" \
                         "runtime: Docker\nsource: foo/bar\n"

    assert expected_user_data == awsjson["Resources"]["AppServerConfig"]["Properties"]["UserData"]["Fn::Base64"]


def test_print_taupage_config_with_ref(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            ec2.security_groups.filter.return_value = [MagicMock(name='app-master-mind', id='sg-007')]
            return ec2
        return MagicMock()

    monkeypatch.setattr('boto3.client', MagicMock())
    monkeypatch.setattr('boto3.resource', my_resource)
    data = {'SenzaInfo': {'StackName': 'test',
                          'Parameters': [{'ApplicationId': {'Description': 'Application ID from kio'}}]},
            'SenzaComponents': [{'Configuration': {'ServerSubnets': {'myregion': ['subnet-123']},
                                                   'Type': 'Senza::Configuration'}},
                                {'AppServer': {'Image': 'AppImage',
                                               'InstanceType': 't2.micro',
                                               'SecurityGroups': ['app-{{Arguments.ApplicationId}}'],
                                               'IamRoles': ['app-{{Arguments.ApplicationId}}'],
                                               'TaupageConfig': {'runtime': 'Docker',
                                                                 'source': 'foo/bar',
                                                                 'ports': {80: 80},
                                                                 'mint_bucket': {'Fn::Join':
                                                                                 ['-',
                                                                                  [{'Ref': 'bucket1'},
                                                                                   '{{ Arguments.ApplicationId}}'
                                                                                   ]
                                                                                  ]},
                                                                 'environment': {'ENV1': {'Ref': 'resource1'},
                                                                                 'ENV2': 'v2'}},
                                               'Type': 'Senza::TaupageAutoScalingGroup'}}]
            }

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd, default_flow_style=False)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123', 'master-mind'],
                               catch_exceptions=False)

    stdout, cfjson = result.output.split('\n', 1)
    assert 'Generating Cloud Formation template.. OK' == stdout
    awsjson = json.loads(cfjson)

    expected_user_data = {"Fn::Join": ["", [
        "#taupage-ami-config\napplication_id: test\napplication_version: '123'\nenvironment:\n  ENV1: ",
        {"Ref": "resource1"},
        "\n  ENV2: v2\nmint_bucket: ",
        {"Fn::Join": ["-", [{"Ref": "bucket1"}, "master-mind"]]},
        "\nnotify_cfn:\n  resource: AppServer\n  stack: test-123" +
        "\nports:\n  80: 80\nruntime: Docker\nsource: foo/bar\n"]]}

    assert expected_user_data == awsjson["Resources"]["AppServerConfig"]["Properties"]["UserData"]["Fn::Base64"]


def test_dump(monkeypatch):
    cf = MagicMock()
    cf.list_stacks.return_value = {'StackSummaries': [{'StackName': 'mystack-1'}]}
    cf.get_template.return_value = {'TemplateBody': {'foo': 'bar'}}
    monkeypatch.setattr('boto3.client', lambda *args: cf)

    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ['dump', 'mystack', '--region=myregion'],
                               catch_exceptions=False)

        assert '{\n    "foo": "bar"\n}' == result.output.rstrip()

        result = runner.invoke(cli, ['dump', 'mystack', '--region=myregion', '-o', 'yaml'],
                               catch_exceptions=False)

        assert 'foo: bar' == result.output.rstrip()


def test_init(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            ec2.security_groups.filter.side_effect = botocore.exceptions.ClientError(
                {'Error': {'Code': 'InvalidGroup.NotFound',
                           'Message': 'Group Not found'}},
                'foobar')
            return ec2
        return MagicMock()

    monkeypatch.setattr('boto3.client', lambda *args: MagicMock())
    monkeypatch.setattr('boto3.resource', my_resource)

    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ['init', 'myapp.yaml', '--region=myregion', '-v', 'test=123',
                                     '-v', 'mint_bucket=mybucket'],
                               catch_exceptions=False, input='1\nsdf\nsdf\n8080\n/\n')
        assert os.path.exists('myapp.yaml')
        with open('myapp.yaml') as fd:
            generated_definition = yaml.safe_load(fd)

    assert 'Generating Senza definition file myapp.yaml.. OK' in result.output
    assert generated_definition['SenzaInfo']['StackName'] == 'sdf'
    assert (generated_definition['SenzaComponents'][1]['AppServer']['TaupageConfig']['application_version']
            == '{{Arguments.ImageVersion}}')


def test_init_opt5(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            ec2.security_groups.filter.side_effect = botocore.exceptions.ClientError(
                {'Error': {'Code': 'InvalidGroup.NotFound',
                           'Message': 'Group Not found'}},
                'foobar')
            return ec2
        return MagicMock()

    monkeypatch.setattr('boto3.client', lambda *args: MagicMock())
    monkeypatch.setattr('boto3.resource', my_resource)

    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ['init', 'myapp.yaml', '--region=myregion', '-v', 'test=123',
                                     '-v', 'mint_bucket=mybucket'],
                               catch_exceptions=False, input='5\nsdf\nsdf\n8080\n/\n')
        assert os.path.exists('myapp.yaml')
        with open('myapp.yaml') as fd:
            generated_definition = yaml.safe_load(fd)

    assert 'Generating Senza definition file myapp.yaml.. OK' in result.output
    assert generated_definition['SenzaInfo']['StackName'] == 'sdf'
    assert (generated_definition['SenzaComponents'][1]['AppServer']['TaupageConfig']['application_version']
            == '{{Arguments.ImageVersion}}')


def test_instances(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            instance = MagicMock()
            instance.id = 'inst-123'
            instance.public_ip_address = '8.8.8.8'
            instance.private_ip_address = '10.0.0.1'
            instance.state = {'Name': 'Test-instance'}
            instance.tags = [{'Key': 'aws:cloudformation:stack-name', 'Value': 'test-1'},
                             {'Key': 'aws:cloudformation:logical-id', 'Value': 'local-id-123'},
                             {'Key': 'StackName', 'Value': 'test'},
                             {'Key': 'StackVersion', 'Value': '1'}]
            instance.launch_time = datetime.datetime.now()
            ec2.instances.filter.return_value = [instance]
            return ec2
        return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'cloudformation':
            cf = MagicMock()
            cf.list_stacks.return_value = {'StackSummaries': [{'StackName': 'test-1'}]}
            return cf
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('boto3.client', my_client)

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['instances', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)

    assert 'Launched\n' in result.output
    assert 'local-id-123' in result.output
    assert 'TEST_INSTANCE' in result.output
    assert 's ago \n' in result.output


def test_console(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            instance = MagicMock()
            instance.id = 'inst-123'
            instance.private_ip_address = '10.0.0.1'
            instance.tags = [{'Key': 'aws:cloudformation:stack-name', 'Value': 'test-1'}]
            instance.console_output.return_value = {'Output': '**MAGIC-CONSOLE-OUTPUT**'}
            ec2.instances.filter.return_value = [instance]
            return ec2
        return MagicMock()

    def my_client(rtype, *args, **kwargs):
        if rtype == 'cloudformation':
            cf = MagicMock()
            cf.list_stacks.return_value = {'StackSummaries': [{'StackName': 'test-1'}]}
            return cf
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('boto3.client', my_client)

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['console', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)
        assert 'Showing last 25 lines of test-1/10.0.0.1..' in result.output
        assert '**MAGIC-CONSOLE-OUTPUT**' in result.output

        result = runner.invoke(cli, ['console', 'foobar', '--region=myregion'],
                               catch_exceptions=False)
        assert '' == result.output

        result = runner.invoke(cli, ['console', '172.31.1.2', '--region=myregion'],
                               catch_exceptions=False)
        assert 'Showing last 25 lines of test-1/10.0.0.1..' in result.output
        assert '**MAGIC-CONSOLE-OUTPUT**' in result.output

        result = runner.invoke(cli, ['console', 'i-123', '--region=myregion'],
                               catch_exceptions=False)
        assert 'Showing last 25 lines of test-1/10.0.0.1..' in result.output
        assert '**MAGIC-CONSOLE-OUTPUT**' in result.output


def test_status(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            instance = MagicMock()
            instance.id = 'inst-123'
            instance.public_ip_address = '8.8.8.8'
            instance.private_ip_address = '10.0.0.1'
            instance.state = {'Name': 'Test-instance'}
            instance.tags = [{'Key': 'aws:cloudformation:stack-name', 'Value': 'test-1'},
                             {'Key': 'aws:cloudformation:logical-id', 'Value': 'local-id-123'},
                             {'Key': 'StackName', 'Value': 'test'},
                             {'Key': 'StackVersion', 'Value': '1'}]
            instance.launch_time = datetime.datetime.utcnow()
            ec2.instances.filter.return_value = [instance]
            return ec2
        return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'cloudformation':
            cf = MagicMock()
            cf.list_stacks.return_value = {'StackSummaries': [{'StackName': 'test-1'}]}
            return cf
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('boto3.client', my_client)

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['status', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)

    assert 'Running' in result.output


def test_resources(monkeypatch):
    def my_resource(rtype, *args):
        return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'cloudformation':
            cf = MagicMock()
            cf.list_stacks.return_value = {'StackSummaries': [{'StackName': 'test-1'}]}
            cf.describe_stack_resources.return_value = {
                'StackResources': [
                    {'LogicalResourceId': 'AppLoadBalancer',
                     'PhysicalResourceId': 'test-1',
                     'ResourceStatus': 'CREATE_COMPLETE',
                     'ResourceType': 'AWS::ElasticLoadBalancing::LoadBalancer',
                     'StackId': 'arn:aws:cloudformation:myregions:123456:stack/test-1/123456',
                     'StackName': 'test-1',
                     'Timestamp': datetime.datetime.utcnow()},
                    {'LogicalResourceId': 'AppServer',
                     'PhysicalResourceId': 'hello-world-v17-AppServer-2AUO7HTN5KB6',
                     'ResourceStatus': 'CREATE_COMPLETE',
                     'ResourceType': 'AWS::AutoScaling::AutoScalingGroup',
                     'StackId': 'arn:aws:cloudformation:myregions:123456:stack/test-1/123456',
                     'StackName': 'test-1',
                     'Timestamp': datetime.datetime.utcnow()},
                ]}
            return cf
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('boto3.client', my_client)

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['resources', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)
    assert 'AppLoadBalancer' in result.output
    assert 'CREATE_COMPLETE' in result.output
    assert 'ElasticLoadBalancing::LoadBalancer' in result.output
    assert 'AutoScalingGroup' in result.output
    assert 'Resource Type' in result.output


def test_domains(monkeypatch):
    senza.traffic.DNS_ZONE_CACHE = {}
    senza.traffic.DNS_RR_CACHE = {}

    def my_resource(rtype, *args):
        if rtype == 'cloudformation':
            res = MagicMock()
            res.resource_type = 'AWS::Route53::RecordSet'
            res.physical_resource_id = 'test-1.example.org'
            res.logical_id = 'VersionDomain'
            res.last_updated_timestamp = datetime.datetime.now()
            res2 = MagicMock()
            res2.resource_type = 'AWS::Route53::RecordSet'
            res2.physical_resource_id = 'mydomain.example.org'
            res2.logical_id = 'MainDomain'
            res2.last_updated_timestamp = datetime.datetime.now()
            stack = MagicMock()
            stack.resource_summaries.all.return_value = [res, res2]
            cf = MagicMock()
            cf.Stack.return_value = stack
            return cf
        return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'cloudformation':
            cf = MagicMock()
            cf.list_stacks.return_value = {'StackSummaries': [{'StackName': 'test-1'}]}
            return cf
        elif rtype == 'route53':
            route53 = MagicMock()
            route53.list_hosted_zones.return_value = {'HostedZones': [{'Name': 'example.org.',
                                                                               'Id': '/hostedzone/123'}]}
            route53.list_resource_record_sets.return_value = {
                'IsTruncated': False,
                'MaxItems': '100',
                'ResourceRecordSets': [
                    {'Name': 'example.org.',
                     'ResourceRecords': [{'Value': 'ns.awsdns.com.'},
                                         {'Value': 'ns.awsdns.org.'}],
                     'TTL': 172800,
                     'Type': 'NS'},
                    {'Name': 'test-1.example.org.',
                     'ResourceRecords': [{'Value': 'test-1-123.myregion.elb.amazonaws.com'}],
                     'TTL': 20,
                     'Type': 'CNAME'},
                    {'Name': 'mydomain.example.org.',
                     'ResourceRecords': [{'Value': 'test-1.example.org'}],
                     'SetIdentifier': 'test-1',
                     'TTL': 20,
                     'Type': 'CNAME',
                     'Weight': 20},
                ]}
            return route53
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('boto3.client', my_client)

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['domains', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)
    assert 'mydomain.example.org' in result.output
    assert 'VersionDomain test-1.example.org          CNAME test-1-123.myregion.elb.amazonaws.com' in result.output
    assert 'MainDomain    mydomain.example.org 20     CNAME test-1.example.org' in result.output


def test_events(monkeypatch):
    def my_resource(rtype, *args):
        return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'cloudformation':
            cf = MagicMock()
            cf.list_stacks.return_value = {'StackSummaries': [{'StackName': 'test-1'}]}
            cf.describe_stack_events.return_value = {'StackEvents': [
                {'EventId': 'af98cac9-eca9-4946-ae23-683acb223b52',
                 'LogicalResourceId': 'test-1',
                 'PhysicalResourceId': 'arn:aws:cloudformation:myregions:123456:stack/test-1/eb559d22-3c',
                 'ResourceStatus': 'CREATE_COMPLETE',
                 'ResourceType': 'AWS::CloudFormation::Stack',
                 'StackId': 'arn:aws:cloudformation:myregions:123456:stack/test-1/123456',
                 'StackName': 'test-1',
                 'Timestamp': datetime.datetime.utcnow()},
                {'EventId': 'AppServer-CREATE_COMPLETE-2015-03-14T09:26:53.000Z',
                 'LogicalResourceId': 'AppServer',
                 'PhysicalResourceId': 'test-1-AppServer-ABCDEFGHIJKL',
                 'ResourceProperties': '{"Tags":[{"PropagateAtLaunch":"true","Value":"test-1","Key":"Name"}]}',
                 'ResourceStatus': 'CREATE_COMPLETE',
                 'ResourceType': 'AWS::AutoScaling::AutoScalingGroup',
                 'StackId': 'arn:aws:cloudformation:myregions:123456:stack/test-1/123456',
                 'StackName': 'test-1',
                 'Timestamp': datetime.datetime.utcnow()},
            ]}

            return cf
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('boto3.client', my_client)

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['events', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)

    assert ' CloudFormation::Stack' in result.output


def test_list(monkeypatch):
    def my_resource(rtype, *args):
        return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'cloudformation':
            cf = MagicMock()
            cf.list_stacks.return_value = {'StackSummaries': [{'StackName': 'test-stack-1',
                                                               'CreationTime': datetime.datetime.utcnow()}]}
            return cf
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('boto3.client', my_client)

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test-stack'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['list', 'myapp.yaml', '--region=myregion'],
                               catch_exceptions=False)

    assert 'test-stack 1' in result.output


def test_images(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'ec2':
            image = MagicMock()
            image.id = 'ami-123'
            image.meta.data.copy.return_value = {'Name': 'BrandNewImage',
                                                 'ImageId': 'ami-123'}
            image.creation_date = datetime.datetime.utcnow().isoformat('T') + 'Z'

            old_image_still_used = MagicMock()
            old_image_still_used.id = 'ami-456'
            old_image_still_used.meta.data.copy.return_value = {'Name': 'OldImage',
                                                                'ImageId': 'ami-456'}
            old_image_still_used.creation_date = (datetime.datetime.utcnow() -
                                                  datetime.timedelta(days=30)).isoformat('T') + 'Z'

            instance = MagicMock()
            instance.id = 'i-777'
            instance.image_id = 'ami-456'
            instance.tags = [{'Key': 'aws:cloudformation:stack-name', 'Value': 'mystack'}]

            ec2 = MagicMock()
            ec2.images.filter.return_value = [image, old_image_still_used]
            ec2.instances.all.return_value = [instance]
            return ec2
        return MagicMock()

    def my_client(rtype, *args):
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('boto3.client', my_client)

    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ['images', '--region=myregion'], catch_exceptions=False)

    assert 'ami-123' in result.output
    assert 'ami-456' in result.output
    assert 'mystack' in result.output


def test_delete(monkeypatch):

    cf = MagicMock()
    stack = {'StackName': 'test-1',
             'CreationTime': datetime.datetime.utcnow()}
    cf.list_stacks.return_value = {'StackSummaries': [stack]}

    def my_resource(rtype, *args):
        return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'cloudformation':
            return cf
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('boto3.client', my_client)

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['delete', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)
        assert 'OK' in result.output

        cf.list_stacks.return_value = {'StackSummaries': [stack, stack]}
        result = runner.invoke(cli, ['delete', 'myapp.yaml', '--region=myregion'],
                               catch_exceptions=False)
        assert 'Please use the "--force" flag if you really want to delete multiple stacks' in result.output

        result = runner.invoke(cli, ['delete', 'myapp.yaml', '--region=myregion', '--force'],
                               catch_exceptions=False)
        assert 'OK' in result.output


def test_create(monkeypatch):
    cf = MagicMock()

    def my_resource(rtype, *args):
        if rtype == 'sns':
            sns = MagicMock()
            topic = MagicMock(arn='arn:123:my-topic')
            sns.topics.all.return_value = [topic]
            return sns
        return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'cloudformation':
            return cf
        return MagicMock()

    monkeypatch.setattr('boto3.client', my_client)
    monkeypatch.setattr('boto3.resource', my_resource)

    runner = CliRunner()

    data = {'SenzaComponents': [{'Config': {'Type': 'Senza::Configuration'}}],
            'SenzaInfo': {'OperatorTopicId': 'my-topic',
                          'Parameters': [{'MyParam': {'Type': 'String'}}, {'ExtraParam': {'Type': 'String'}}],
                          'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '1', 'my-param-value',
                                     'extra-param-value'],
                               catch_exceptions=False)
        assert 'DRY-RUN' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--region=myregion', '1', 'my-param-value',
                                     'extra-param-value'],
                               catch_exceptions=False)
        assert 'OK' in result.output

        cf.create_stack.side_effect = botocore.exceptions.ClientError({'Error': {'Code': 'AlreadyExistsException',
                                                                                 'Message': 'already exists expired'}},
                                                                      'foobar')
        result = runner.invoke(cli, ['create', 'myapp.yaml', '--region=myregion', '1', 'my-param-value',
                                     'extra-param-value'],
                               catch_exceptions=True)
        assert 'Stack test-1 already exists' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--region=myregion', 'abcde' * 25, 'my-param-value',
                                     'extra-param-value'],
                               catch_exceptions=True)
        assert 'cannot exceed 128 characters. Please choose another name/version.' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2'],
                               catch_exceptions=True)
        assert 'Missing parameter' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2', 'p1', 'p2', 'p3',
                                     'p4'],
                               catch_exceptions=True)
        assert 'Too many parameters given' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2', 'my-param-value',
                                     'ExtraParam=extra-param-value'],
                               catch_exceptions=True)
        assert 'OK' in result.output

        # checks that equal signs are OK in the keyword param value
        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2', 'my-param-value',
                                     'ExtraParam=extra=param=value'],
                               catch_exceptions=True)
        assert 'OK' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2',
                                     'UnknownParam=value'],
                               catch_exceptions=True)
        assert 'Unrecognized keyword parameter' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2', 'my-param-value',
                                     'MyParam=param-value-again'],
                               catch_exceptions=True)
        assert 'Parameter specified multiple times' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2',
                                     'MyParam=my-param-value', 'MyParam=param-value-again'],
                               catch_exceptions=True)
        assert 'Parameter specified multiple times' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2',
                                     'MyParam=my-param-value', 'positional'],
                               catch_exceptions=True)
        assert 'Positional parameters must not follow keywords' in result.output


def test_update(monkeypatch):
    cf = MagicMock()

    def my_client(rtype, *args):
        if rtype == 'cloudformation':
            return cf
        return MagicMock()

    monkeypatch.setattr('boto3.client', my_client)

    runner = CliRunner()

    data = {'SenzaComponents': [{'Config': {'Type': 'Senza::Configuration'}}],
            'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['update', 'myapp.yaml', '--dry-run', '--region=myregion', '1'],
                               catch_exceptions=False)
        assert 'DRY-RUN' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)
        assert 'OK' in result.output


def test_traffic(monkeypatch):
    route53 = MagicMock(name='r53conn')

    def my_resource(rtype, *args):
        return MagicMock()

    def my_client(rtype, *args, **kwargs):
        if rtype == 'route53':
            return route53
        return MagicMock()

    monkeypatch.setattr('boto3.client', my_client)
    monkeypatch.setattr('boto3.resource', my_resource)

    stacks = [
        StackVersion('myapp', 'v1', ['myapp.example.org'], ['some-lb'], ['some-arn']),
        StackVersion('myapp', 'v2', ['myapp.example.org'], ['another-elb'], ['some-arn']),
        StackVersion('myapp', 'v3', ['myapp.example.org'], ['elb-3'], ['some-arn']),
        StackVersion('myapp', 'v4', ['myapp.example.org'], ['elb-4'], ['some-arn']),
    ]
    monkeypatch.setattr('senza.traffic.get_stack_versions', MagicMock(return_value=stacks))

    # start creating mocking of the route53 record sets and Application Versions
    # this is a lot of dirty and nasty code. Please, somebody help this code.

    def record(dns_identifier, weight):
        return {'Name': 'myapp.example.org.',
                'Weight': str(weight),
                'SetIdentifier': dns_identifier,
                'Type': 'CNAME'}

    rr = MagicMock()
    records = collections.OrderedDict()

    for ver, percentage in [('v1', 60),
                            ('v2', 30),
                            ('v3', 10),
                            ('v4', 0)]:
        dns_identifier = 'myapp-{}'.format(ver)
        records[dns_identifier] = record(dns_identifier, percentage * PERCENT_RESOLUTION)

    rr.__iter__ = lambda x: iter(records.values())
    monkeypatch.setattr('senza.traffic.get_records', MagicMock(return_value=rr))
    monkeypatch.setattr('senza.traffic.get_zone', MagicMock(return_value={'Id': 'dummyid'}))

    def change_rr_set(HostedZoneId, ChangeBatch):
        for change in ChangeBatch['Changes']:
            action = change['Action']
            rrset = change['ResourceRecordSet']
            if action == 'UPSERT':
                records[rrset['SetIdentifier']] = rrset.copy()
            elif action == 'DELETE':
                records[rrset['SetIdentifier']]['Weight'] = 0

    route53.change_resource_record_sets = change_rr_set

    runner = CliRunner()

    common_opts = ['traffic', '--region=my-region', 'myapp']

    def run(opts):
        result = runner.invoke(cli, common_opts + opts, catch_exceptions=False)
        assert 'Setting weights for myapp.example.org..' in result.output
        return result

    def weights():
        return [r['Weight'] for r in records.values()]

    with runner.isolated_filesystem():
        run(['v4', '100'])
        assert weights() == [0, 0, 0, 200]

        run(['v3', '10'])
        assert weights() == [0, 0, 20, 180]

        run(['v2', '0.5'])
        assert weights() == [0, 1, 20, 179]

        run(['v1', '1'])
        assert weights() == [2, 1, 19, 178]

        run(['v4', '95'])
        assert weights() == [1, 1, 13, 185]

        run(['v4', '100'])
        assert weights() == [0, 0, 0, 200]

        run(['v4', '10'])
        assert weights() == [0, 0, 0, 200]

        run(['v4', '0'])
        assert weights() == [0, 0, 0, 0]


def test_AccountArguments(monkeypatch):
    senza.traffic.DNS_ZONE_CACHE = {}
    senza_aws = MagicMock()
    senza_aws.get_account_alias.return_value = 'test-cli'
    senza_aws.get_account_id.return_value = '123456'
    boto3 = MagicMock()
    boto3.list_hosted_zones.return_value = {'HostedZones': [{'Name': 'test.example.net'}]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    monkeypatch.setattr('senza.cli.get_account_alias', MagicMock(return_value='test-cli'))
    monkeypatch.setattr('senza.cli.get_account_id', MagicMock(return_value='98741256325'))

    test = AccountArguments('test-region')

    assert test.Region == 'test-region'
    assert test.AccountAlias == 'test-cli'
    assert test.AccountID == '98741256325'
    assert test.Domain == 'test.example.net'
    assert test.TeamID == 'cli'


def test_patch(monkeypatch):
    boto3 = MagicMock()
    boto3.list_stacks.return_value = {'StackSummaries': [{'StackName': 'myapp-1'}]}
    boto3.describe_stack_resources.return_value = {'StackResources': [{'ResourceType': 'AWS::AutoScaling::AutoScalingGroup', 'PhysicalResourceId': 'myasg'}]}
    group = {'AutoScalingGroupName': 'myasg'}
    boto3.describe_auto_scaling_groups.return_value = {'AutoScalingGroups': [group]}
    image = MagicMock()
    image.id = 'latesttaupage-123'

    props = {}

    def patch_auto_scaling_group(group, region, properties):
        props.update(properties)


    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    monkeypatch.setattr('senza.cli.find_taupage_image', MagicMock(return_value=image))
    monkeypatch.setattr('senza.cli.patch_auto_scaling_group', patch_auto_scaling_group)
    runner = CliRunner()
    result = runner.invoke(cli, ['patch', 'myapp', '1', '--image=latest', '--region=myregion'],
                           catch_exceptions=False)

    assert props['ImageId'] == 'latesttaupage-123'
    assert 'Patching Auto Scaling Group myasg' in result.output


def test_respawn(monkeypatch):
    boto3 = MagicMock()
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    monkeypatch.setattr('senza.cli.get_auto_scaling_groups', lambda *args: 'myasg')
    monkeypatch.setattr('senza.cli.respawn_auto_scaling_group', lambda *args, **kwargs: None)
    runner = CliRunner()
    result = runner.invoke(cli, ['respawn', 'myapp', '1', '--region=myregion'],
                           catch_exceptions=False)


def test_scale(monkeypatch):
    boto3 = MagicMock()
    boto3.list_stacks.return_value = {'StackSummaries': [{'StackName': 'myapp-1'}]}
    boto3.describe_stack_resources.return_value = {'StackResources': [{'ResourceType': 'AWS::AutoScaling::AutoScalingGroup', 'PhysicalResourceId': 'myasg'}]}
    # NOTE: we are using invalid MinSize (< capacity) here to get one more line covered ;-)
    group = {'AutoScalingGroupName': 'myasg', 'DesiredCapacity': 1, 'MinSize': 3, 'MaxSize': 1}
    boto3.describe_auto_scaling_groups.return_value = {'AutoScalingGroups': [group]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    runner = CliRunner()
    result = runner.invoke(cli, ['scale', 'myapp', '1', '2', '--region=myregion'],
                           catch_exceptions=False)
    assert 'Scaling myasg from 1 to 2 instances' in result.output


