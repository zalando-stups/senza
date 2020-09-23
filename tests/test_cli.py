import collections
import datetime
import json
import os
from contextlib import contextmanager

from typing import List, Dict
from unittest.mock import MagicMock, mock_open

import botocore.exceptions
import pytest
import senza.traffic
import yaml
import base64
from click.testing import CliRunner

from senza.components.elastigroup import ELASTIGROUP_RESOURCE_TYPE
from senza.aws import SenzaStackSummary
from senza.cli import (KeyValParamType, StackReference,
                       all_with_version, create_cf_template, failure_event,
                       get_console_line_style, get_stack_refs, is_ip_address,
                       decrypt_parameters)
from senza.definitions import AccountArguments
from senza.exceptions import InvalidDefinition
from senza.manaus.exceptions import ELBNotFound, StackNotFound, StackNotUpdated
from senza.manaus.route53 import RecordType, Route53Record
from senza.subcommands.root import cli
from senza.traffic import PERCENT_RESOLUTION, StackVersion

from fixtures import (HOSTED_ZONE_EXAMPLE_NET,  # noqa: F401
                      HOSTED_ZONE_EXAMPLE_ORG, boto_client, boto_resource,
                      disable_version_check, valid_regions)


def test_invalid_definition():
    data = {}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=aa-fakeregion-1', '123'], catch_exceptions=False)

    assert 'error: invalid value for' in result.output.lower()


def test_file_not_found():
    data = {}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli,
                               ['print', 'notfound.yaml', '--region=aa-fakeregion-1', '123'],
                               catch_exceptions=False)

    assert '"notfound.yaml" not found' in result.output


def test_parameter_file_not_found():
    data = {'SenzaInfo': {'StackName': 'test'}, 'Resources': {'MyQueue': {'Type': 'AWS::SQS::Queue'}}}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli,
                               ['print', '--parameter-file', 'notfound.yaml',
                                'myapp.yaml', '--region=aa-fakeregion-1', '123'],
                               catch_exceptions=False)

    assert 'read parameter file "notfound.yaml"' in result.output


def test_parameter_file_found(monkeypatch):
    monkeypatch.setattr('boto3.client', lambda *args: MagicMock())

    data = {'SenzaInfo': {'StackName': 'test',
                          'Parameters': [{'ApplicationId': {'Description': 'Application ID from kio'}}]},
            'Resources': {'MyQueue': {'Type': 'AWS::SQS::Queue'}}}
    param_data = {'ApplicationId': 'test-app-id'}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        with open('parameter.yaml', 'w') as fd:
            yaml.dump(param_data, fd)

        result = runner.invoke(cli,
                               ['print', '--parameter-file', 'parameter.yaml',
                                'myapp.yaml', '--region=aa-fakeregion-1', '123'],
                               catch_exceptions=False)

    assert 'Generating Cloud Formation template.. OK' in result.output


def test_parameter_file_syntax_error():
    data = {'SenzaInfo': {'StackName': 'test',
                          'Parameters': [{'ApplicationId': {'Description': 'Application ID from kio'}}]},
            'Resources': {'MyQueue': {'Type': 'AWS::SQS::Queue'}}}
    param_data = "'ApplicationId': ["

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        with open('parameter.yaml', 'w') as fd:
            fd.write(param_data)

        result = runner.invoke(cli, ['print',
                                     '--parameter-file', 'parameter.yaml',
                                     'myapp.yaml',
                                     '--region=aa-fakeregion-1', '123'],
                               catch_exceptions=False)

    assert 'Error: Error while parsing a flow node' in result.output


def test_print_minimal(monkeypatch):
    monkeypatch.setattr('boto3.client', lambda *args: MagicMock())

    data = {'SenzaInfo': {'StackName': 'test'}, 'Resources': {'MyQueue': {'Type': 'AWS::SQS::Queue'}}}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=aa-fakeregion-1', '123'],
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

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=aa-fakeregion-1', '123'],
                               catch_exceptions=False)

    assert 'AWSTemplateFormatVersion' in result.output
    assert 'subnet-123' in result.output


def test_region_validation(monkeypatch):
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

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=invalid-region', '123'],
                               catch_exceptions=False)

    assert ('Region must be one of the following AWS regions:' in result.output)


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

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=aa-fakeregion-1', '123', 'master-mind'],
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

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=aa-fakeregion-1', '123'],
                               catch_exceptions=False)
    assert '"StackName": "test-aa-fakeregion-1",' in result.output
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

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=aa-fakeregion-1', '123', 'b'],
                               catch_exceptions=False)
    assert '"StackName": "test-aa-fakeregion-1-b",' in result.output
    assert 'AppImage-dummy-0123456789' in result.output


def test_print_auto(monkeypatch, boto_client, boto_resource, disable_version_check):  # noqa: F811
    senza.traffic.DNS_ZONE_CACHE = {}

    data = {'SenzaInfo': {'StackName': 'test',
                          'OperatorTopicId': 'mytopic',
                          'Parameters': [{'ImageVersion': {'Description': ''}}]},
            'SenzaComponents': [{'Configuration': {'Type': 'Senza::StupsAutoConfiguration'}},
                                {'AppServer': {'Type': 'Senza::TaupageAutoScalingGroup',
                                               'ElasticLoadBalancer': 'AppLoadBalancer',
                                               'InstanceType': 't2.micro',
                                               'TaupageConfig': {'runtime': 'Docker',
                                                                 'source': 'foo/bar:{{Arguments.ImageVersion}}'},
                                               'IamRoles': [{'Stack': 'stack1', 'LogicalId': 'ReferencedRole'}],
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

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=aa-fakeregion-1', '123', '1.0-SNAPSHOT'],
                               catch_exceptions=False)
    # no stdout/stderr seperation with runner.invoke...
    stdout, cfjson = result.output.split('\n', 1)
    assert 'Generating Cloud Formation template.. OK' == stdout
    data = json.loads(cfjson)
    assert 'AWSTemplateFormatVersion' in data.keys()
    assert 'subnet-abc123' in data['Mappings']['ServerSubnets']['aa-fakeregion-1']['Subnets']
    assert 'subnet-ghi789' not in data['Mappings']['ServerSubnets']['aa-fakeregion-1']['Subnets']
    assert 'subnet-ghi789' in data['Mappings']['LoadBalancerSubnets']['aa-fakeregion-1']['Subnets']
    assert 'source: foo/bar:1.0-SNAPSHO' in data['Resources']['AppServerConfig']['Properties']['UserData']['Fn::Base64']
    assert 'ELB' == data['Resources']['AppServer']['Properties']['HealthCheckType']
    assert 'my-referenced-role' in data['Resources']['AppServerInstanceProfile']['Properties']['Roles']


def test_print_default_value(monkeypatch, boto_client, boto_resource):  # noqa: F811
    senza.traffic.DNS_ZONE_CACHE = {}

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

        result = runner.invoke(cli, ['print', 'myapp.yaml',
                                     '--region=aa-fakeregion-1',
                                     '123', '1.0-SNAPSHOT', 'extra value'],
                               catch_exceptions=False)
        assert 'DefParam: DefValue\\n' in result.output
        assert 'ExtraParam: extra value\\n' in result.output

        result = runner.invoke(cli, ['print', 'myapp.yaml',
                                     '--region=aa-fakeregion-1',
                                     '123', '1.0-SNAPSHOT', 'extra value',
                                     'other def value'],
                               catch_exceptions=False)
        assert 'DefParam: other def value\\n' in result.output
        assert 'ExtraParam: extra value\\n' in result.output


def test_print_taupage_config_without_ref(monkeypatch, disable_version_check):  # noqa: F811
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

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=aa-fakeregion-1', '123', 'master-mind'],
                               catch_exceptions=False)

    stdout, cfjson = result.output.split('\n', 1)
    assert 'Generating Cloud Formation template.. OK' == stdout
    awsjson = json.loads(cfjson)

    expected_user_data = "#taupage-ami-config\napplication_id: test\napplication_version: '123'\n" \
                         "environment:\n  ENV1: v1\n  ENV2: v2\nmint_bucket: zalando-mint-bucket\n" \
                         "notify_cfn:\n  resource: AppServer\n  stack: test-123\nports:\n  80: 80\n" \
                         "runtime: Docker\nsource: foo/bar\n"

    assert expected_user_data == awsjson["Resources"]["AppServerConfig"]["Properties"]["UserData"]["Fn::Base64"]


def test_print_taupage_config_with_ref(monkeypatch, disable_version_check):  # noqa: F811
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

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=aa-fakeregion-1', '123', 'master-mind'],
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


def test_dump(monkeypatch, disable_version_check):  # noqa: F811
    cf = MagicMock()
    cf.list_stacks.return_value = {'StackSummaries': [{'StackName': 'mystack-1',
                                                       'CreationTime': '2016-06-14'}]}
    cf.get_template.return_value = {'TemplateBody': {'foo': 'bar'}}
    monkeypatch.setattr('boto3.client', lambda *args: cf)

    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ['dump', 'mystack', '--region=aa-fakeregion-1'],
                               catch_exceptions=False)

        assert '{\n    "foo": "bar"\n}' == result.output.rstrip()

        result = runner.invoke(cli, ['dump', 'mystack', '--region=aa-fakeregion-1', '-o', 'yaml'],
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
        result = runner.invoke(cli, ['init', 'myapp.yaml', '--region=aa-fakeregion-1', '-v', 'test=123',
                                     '-v', 'mint_bucket=mybucket'],
                               catch_exceptions=False, input='1\nsdf\nsdf\n8080\n/\n')
        assert os.path.exists('myapp.yaml')
        with open('myapp.yaml') as fd:
            generated_definition = yaml.safe_load(fd)

    assert 'Generating Senza definition file myapp.yaml.. OK' in result.output
    assert generated_definition['SenzaInfo']['StackName'] == 'sdf'
    senza_app_server = generated_definition['SenzaComponents'][1]['AppServer']
    assert (senza_app_server['TaupageConfig']['application_version'] == '{{Arguments.ImageVersion}}')


def test_init_opt2(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            ec2.vpcs.all.return_value = [MagicMock(vpc_id='vpc-123')]
            vpc = dict()
            ec2.Vpc.return_value = vpc
            return ec2
        elif rtype == 'route53':
            route53 = MagicMock()
            route53.list_hosted_zones.return_value = {'HostedZones': [HOSTED_ZONE_EXAMPLE_ORG]}
            return route53
        return MagicMock()

    monkeypatch.setattr('boto3.client', lambda *args: MagicMock())
    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('senza.cli.AccountArguments', MagicMock())

    runner = CliRunner()

    with runner.isolated_filesystem():

        input = ['2'] + ['Y'] * 30
        result = runner.invoke(cli, ['init', 'spilo.yaml', '--region=aa-fakeregion-1'], input='\n'.join(input))
        assert 'Generating Senza definition file' in result.output
        assert 'Do you wish to encrypt these passwords using KMS' in result.output

        input = ['2'] + ['N'] * 30
        result = runner.invoke(cli, ['init', 'spilo.yaml', '--region=aa-fakeregion-1'], input='\n'.join(input))
        assert 'Generating Senza definition file' in result.output
        assert 'Do you wish to encrypt these passwords using KMS' in result.output


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
        result = runner.invoke(cli, ['init', 'myapp.yaml', '--region=aa-fakeregion-1', '-v', 'test=123',
                                     '-v', 'mint_bucket=mybucket'],
                               catch_exceptions=False, input='5\nsdf\nsdf\n8080\n/\n')
        assert os.path.exists('myapp.yaml')
        with open('myapp.yaml') as fd:
            generated_definition = yaml.safe_load(fd)

    assert 'Generating Senza definition file myapp.yaml.. OK' in result.output
    assert generated_definition['SenzaInfo']['StackName'] == 'sdf'
    senza_appserver = generated_definition['SenzaComponents'][1]['AppServer']
    assert (senza_appserver['TaupageConfig']['application_version'] == '{{Arguments.ImageVersion}}')


def test_instances(monkeypatch):
    def my_resource(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            instance = MagicMock()
            instance.id = 'inst-123'
            instance.public_ip_address = '8.8.8.8'
            instance.private_ip_address = '10.0.0.1'
            instance.state = {'Name': 'Test-instance'}
            instance.tags = [{'Key': 'Name', 'Value': 'test-1'},
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
        result = runner.invoke(cli, ['instances', 'myapp.yaml', '--region=aa-fakeregion-1', '1'],
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

    def my_resource_empty(rtype, *args):
        if rtype == 'ec2':
            ec2 = MagicMock()
            ec2.instances.filter.return_value = []
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
        result = runner.invoke(cli, ['console', 'myapp.yaml', '--region=aa-fakeregion-1', '1'],
                               catch_exceptions=False)
        assert 'Showing last 25 lines of test-1/10.0.0.1..' in result.output
        assert '**MAGIC-CONSOLE-OUTPUT**' in result.output

        result = runner.invoke(cli, ['console', 'stacknotfound', '--region=aa-fakeregion-1'],
                               catch_exceptions=False)
        assert "No stack matching 'stacknotfound'." in result.output

        result = runner.invoke(cli, ['console', 'stacknotfound', 'ver1', '--region=aa-fakeregion-1'],
                               catch_exceptions=False)
        assert "No stack matching 'stacknotfound' with version 'ver1'." in result.output

        result = runner.invoke(cli, ['console', '172.31.1.2', '--region=aa-fakeregion-1'],
                               catch_exceptions=False)
        assert 'Showing last 25 lines of test-1/10.0.0.1..' in result.output
        assert '**MAGIC-CONSOLE-OUTPUT**' in result.output

        result = runner.invoke(cli, ['console', 'i-123', '--region=aa-fakeregion-1'],
                               catch_exceptions=False)
        assert 'Showing last 25 lines of test-1/10.0.0.1..' in result.output
        assert '**MAGIC-CONSOLE-OUTPUT**' in result.output

        monkeypatch.setattr('boto3.resource', my_resource_empty)

        result = runner.invoke(cli, ['console', 'i-notfound', '--region=aa-fakeregion-1'],
                               catch_exceptions=False)
        assert "No EC2 instance with id 'i-notfound'." in result.output

        result = runner.invoke(cli, ['console', '--region=aa-fakeregion-1'], catch_exceptions=False)
        assert "No EC2 instances in region 'aa-fakeregion-1'." in result.output


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
            cf.list_stacks.return_value = {'StackSummaries': [{'StackName': 'test-1',
                                                               'CreationTime': '2016-06-14'}]}
            return cf
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('boto3.client', my_client)

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['status', 'myapp.yaml', '--region=aa-fakeregion-1', '1'],
                               catch_exceptions=False)

    assert 'Running' in result.output


def test_resources(monkeypatch):
    def my_resource(rtype, *args):
        return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'cloudformation':
            cf = MagicMock()
            cf.list_stacks.return_value = {'StackSummaries': [{'StackName': 'test-1',
                                                               'CreationTime': '2016-06-14'}]}
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
        result = runner.invoke(cli, ['resources', 'myapp.yaml', '--region=aa-fakeregion-1', '1'],
                               catch_exceptions=False)
    assert 'AppLoadBalancer' in result.output
    assert 'CREATE_COMPLETE' in result.output
    assert 'ElasticLoadBalancing::LoadBalancer' in result.output
    assert 'AutoScalingGroup' in result.output
    assert 'Resource Type' in result.output


def test_domains(monkeypatch, boto_resource, boto_client):  # noqa: F811
    senza.traffic.DNS_ZONE_CACHE = {}
    senza.traffic.DNS_RR_CACHE = {}

    boto_client['route53'].list_hosted_zones.return_value = {'HostedZones': [HOSTED_ZONE_EXAMPLE_ORG]}

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test',
                          'CreationTime': '2016-06-14'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['domains', 'myapp.yaml', '--region=aa-fakeregion-1', '1'],
                               catch_exceptions=False)
    assert 'mydomain.example.org' in result.output
    assert 'VersionDomain test-1.example.org          CNAME test-1-123.myregion.elb.amazonaws.com' in result.output
    assert 'VersionDomain test-2.example.org          A     test-2-123.myregion.elb.amazonaws.com' in result.output
    assert 'MainDomain    mydomain.example.org 20     CNAME test-1.example.org' in result.output


def test_events(monkeypatch):
    def my_resource(rtype, *args):
        return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'cloudformation':
            cf = MagicMock()
            cf.list_stacks.return_value = {'StackSummaries': [{'StackName': 'test-1',
                                                               'CreationTime': '2016-06-01'}]}
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

    data = {'SenzaInfo': {'StackName': 'test'},
            'CreationTime': '2016-06-14'}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['events', 'myapp.yaml', '--region=aa-fakeregion-1', '1'],
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
        result = runner.invoke(cli, ['list', 'myapp.yaml', '--region=aa-fakeregion-1'],
                               catch_exceptions=False)

    assert 'test-stack 1' in result.output


def test_list_version(monkeypatch):
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
        result = runner.invoke(cli, ['list', 'myapp.yaml', '--region=aa-fakeregion-1', '--field=version'],
                               catch_exceptions=False)

    assert '1' in result.output
    assert 'test-stack' not in result.output


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
        result = runner.invoke(cli, ['images', '--region=aa-fakeregion-1'], catch_exceptions=False)

    assert 'ami-123' in result.output
    assert 'ami-456' in result.output
    assert 'mystack' in result.output


def test_delete(monkeypatch, boto_resource, boto_client):  # noqa: F811

    stack = {'StackName': 'test-1',
             'StackId': 'test-1',
             'CreationTime': datetime.datetime.utcnow()}

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['delete', 'myapp.yaml', '--region=aa-fakeregion-1', '1'],
                               catch_exceptions=False)
        assert 'OK' in result.output

        cf = boto_client['cloudformation']
        cf.list_stacks.return_value = {
            'StackSummaries': [stack, stack]
        }

        result = runner.invoke(cli, ['delete', 'myapp.yaml', '--region=aa-fakeregion-1'],
                               catch_exceptions=False)
        assert 'Please use the "--force" flag if you really want to delete multiple stacks' in result.output

        result = runner.invoke(cli, ['delete', 'myapp.yaml', '--region=aa-fakeregion-1', '--force'],
                               catch_exceptions=False)
        assert 'OK' in result.output

        # stack name does not exist
        result = runner.invoke(cli, ['delete', 'not-exist', 'v2', '--region=aa-fakeregion-1',
                                     '--force'], catch_exceptions=False)
        assert 'Stack not-exist not found!' in result.output
        assert result.exit_code == 1

        # ignore the fact that the stack does not exist
        result = runner.invoke(cli, ['delete', 'not-exist', 'v2', '--region=aa-fakeregion-1',
                                     '--ignore-non-existent'],
                               catch_exceptions=False)
        assert 'Stack not-exist not found!' not in result.output
        assert result.exit_code == 0


def test_delete_interactive(monkeypatch, boto_client, boto_resource):  # noqa: F811
    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli,
                               ['delete', 'myapp.yaml', '--region=aa-fakeregion-1', '-i', '1'],
                               input='n\n',
                               catch_exceptions=False)
        assert "Delete 'test-1'" in result.output
        assert "OK" not in result.output

        result = runner.invoke(cli,
                               ['delete', 'myapp.yaml', '--region=aa-fakeregion-1',
                                '-i', '1'],
                               input='y\n',
                               catch_exceptions=False)
        assert "Delete 'test-1'" in result.output
        assert "OK" in result.output


def test_delete_with_traffic(monkeypatch, boto_resource, boto_client):  # noqa: F811

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    mock_route53 = MagicMock()

    mock_route53.return_value = [MagicMock(spec=Route53Record,
                                           set_identifier='test-1',
                                           weight=200)]
    monkeypatch.setattr('senza.manaus.cloudformation.Route53.get_records',
                        mock_route53)

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['delete', 'myapp.yaml', '--region=aa-fakeregion-1'],
                               catch_exceptions=False)
        assert 'Stack test-1 has traffic!' in result.output

        result = runner.invoke(cli, ['delete', 'myapp.yaml', '--region=aa-fakeregion-1', '--force'],
                               catch_exceptions=False)
        assert 'OK' in result.output


def test_decrypt_parameters(monkeypatch):
    def my_client(service_name, region_name, *args):
        if service_name == 'kms':
            kms = MagicMock()
            kms.decrypt.return_value = {
                'KeyId': 'string',
                'Plaintext': bytes('spotinst-decrypted-token', 'UTF-8')
            }
            return kms
        return MagicMock()

    monkeypatch.setattr('boto3.client', my_client)

    b64_encoded_key = base64.b64encode(b'some-encrypted-string')
    definition = {
        'Mappings': {
            'Senza': {
                'Info': {
                    'SpotinstAccessToken': 'senza:kms:' + b64_encoded_key.decode("utf-8"),
                    'SomeOtherProperty': 'some-value'
                }
            }
        }
    }

    decrypted_definition = decrypt_parameters(definition, 'some-region-1')

    assert decrypted_definition["Mappings"]["Senza"]["Info"]['SpotinstAccessToken'] == 'spotinst-decrypted-token'
    assert decrypted_definition["Mappings"]["Senza"]["Info"]['SomeOtherProperty'] == 'some-value'


def test_decrypt_parameters_failed(monkeypatch):
    def my_client(service_name, region_name, *args):
        if service_name == 'kms':
            kms = MagicMock()
            kms.decrypt.side_effect = botocore.exceptions.ClientError({'Error': {'Code': 'KeyUnavailableException',
                                                                                 'Message': 'Key is unavailable'}},
                                                                      'foobar')
            return kms
        return MagicMock()

    monkeypatch.setattr('boto3.client', my_client)

    b64_encoded_key = base64.b64encode(b'some-encrypted-string')
    definition = {
        'Mappings': {
            'Senza': {
                'Info': {
                    'SpotinstAccessToken': 'senza:kms:' + b64_encoded_key.decode("utf-8"),
                    'SomeOtherProperty': 'some-value'
                }
            }
        }
    }

    try:
        decrypt_parameters(definition, 'some-region-1')
    except botocore.exceptions.ClientError as client_error:
        error = client_error.response.get('Error', {})
        error_code = error.get('Code')
        assert error_code == 'KeyUnavailableException'
        return

    assert False


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

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run',
                                     '--region=aa-fakeregion-1', '1',
                                     'my-param-value', 'extra-param-value'],
                               catch_exceptions=False)
        assert 'DRY-RUN' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--region=aa-fakeregion-1', '1', 'my-param-value',
                                     'extra-param-value'],
                               catch_exceptions=False)
        assert 'OK' in result.output

        cf.create_stack.side_effect = botocore.exceptions.ClientError({'Error': {'Code': 'AlreadyExistsException',
                                                                                 'Message': 'already exists expired'}},
                                                                      'foobar')
        result = runner.invoke(cli, ['create', 'myapp.yaml', '--region=aa-fakeregion-1', '1', 'my-param-value',
                                     'extra-param-value'],
                               catch_exceptions=True)
        assert 'Stack test-1 already exists' in result.output

        result = runner.invoke(cli, ['create', '--update-if-exists', 'myapp.yaml',
                                     '--region=aa-fakeregion-1', '1',
                                     'my-param-value',
                                     'extra-param-value'],
                               catch_exceptions=True)
        assert 'Updating Cloud Formation stack test-1' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--region=aa-fakeregion-1', 'abcde' * 25, 'my-param-value',
                                     'extra-param-value'],
                               catch_exceptions=True)
        assert 'cannot exceed 128 characters. Please choose another name/version.' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run',
                                     '--region=aa-fakeregion-1', '2'],
                               catch_exceptions=True)
        assert 'Missing parameter' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run',
                                     '--region=aa-fakeregion-1', '2', 'p1', 'p2', 'p3',
                                     'p4'],
                               catch_exceptions=True)
        assert 'Too many parameters given' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run',
                                     '--region=aa-fakeregion-1', '2',
                                     'my-param-value',
                                     'ExtraParam=extra-param-value'],
                               catch_exceptions=True)
        assert 'OK' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run',
                                     '--tag', 'key=tag_value',
                                     '--region=aa-fakeregion-1', '2',
                                     'my-param-value', 'ExtraParam=extra-param-value'],
                               catch_exceptions=True)
        assert 'OK' in result.output
        assert "'Key': 'key'" in result.output
        assert "'Value': 'tag_value'" in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run',
                                     '--tag', 'key=tag_value',
                                     '--tag', 'key2=value2',
                                     '--region=aa-fakeregion-1',
                                     '2', 'my-param-value',
                                     'ExtraParam=extra-param-value'],
                               catch_exceptions=True)
        assert 'OK' in result.output
        assert "'Key': 'key'" in result.output
        assert "'Key': 'key2'" in result.output

        # checks that equal signs are OK in the keyword param value
        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run',
                                     '--region=aa-fakeregion-1', '2',
                                     'my-param-value',
                                     'ExtraParam=extra=param=value'],
                               catch_exceptions=True)
        assert 'OK' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run',
                                     '--region=aa-fakeregion-1', '2',
                                     'UnknownParam=value'],
                               catch_exceptions=True)
        assert 'Unrecognized keyword parameter' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run',
                                     '--region=aa-fakeregion-1', '2',
                                     'my-param-value', 'MyParam=param-value-again'],
                               catch_exceptions=True)
        assert 'Parameter specified multiple times' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run',
                                     '--region=aa-fakeregion-1', '2',
                                     'MyParam=my-param-value',
                                     'MyParam=param-value-again'],
                               catch_exceptions=True)
        assert 'Parameter specified multiple times' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run',
                                     '--region=aa-fakeregion-1', '2',
                                     'MyParam=my-param-value', 'positional'],
                               catch_exceptions=True)
        assert 'Positional parameters must not follow keywords' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run',
                                     '--tag', 'key=value', '--tag', 'badtag',
                                     '--region=aa-fakeregion-1', '2',
                                     'my-param-value', 'ExtraParam=extra-param-value'],
                               catch_exceptions=True)
        assert 'Invalid tag badtag. Tags should be in the form of key=value' in result.output


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

        result = runner.invoke(cli, ['update', 'myapp.yaml', '--dry-run', '--region=aa-fakeregion-1', '1'],
                               catch_exceptions=False)
        assert 'DRY-RUN' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--region=aa-fakeregion-1', '1'],
                               catch_exceptions=False)
        assert 'OK' in result.output


def test_traffic(monkeypatch, boto_client, boto_resource):  # noqa: F811
    stacks = [
        StackVersion('myapp', 'v1', ['myapp.zo.ne'],
                     ['some-lb.eu-central-1.elb.amazonaws.com'], ['some-arn']),
        StackVersion('myapp', 'v2', ['myapp.zo.ne'],
                     ['another-elb.eu-central-1.elb.amazonaws.com'], ['some-arn']),
        StackVersion('myapp', 'v3', ['myapp.zo.ne'],
                     ['elb-3.eu-central-1.elb.amazonaws.com'], ['some-arn']),
        StackVersion('myapp', 'v4', ['myapp.zo.ne'],
                     ['elb-4.eu-central-1.elb.amazonaws.com'], ['some-arn']),
    ]
    monkeypatch.setattr('senza.traffic.get_stack_versions',
                        MagicMock(return_value=stacks))

    referenced_stacks = [
        SenzaStackSummary({'StackName': s.name, 'StackStatus': 'UPDATE_COMPLETE'})
        for s in stacks]
    monkeypatch.setattr('senza.cli.get_stacks', MagicMock(name="fake_get_stacks", return_value=referenced_stacks))

    # start creating mocking of the route53 record sets and Application Versions
    # this is a lot of dirty and nasty code. Please, somebody help this code.

    def record(dns_identifier, weight):
        return Route53Record(name='myapp.zo.ne.',
                             type=RecordType.A,
                             weight=weight,
                             set_identifier=dns_identifier)

    rr = MagicMock()
    records = collections.OrderedDict()

    for ver, percentage in [('v1', 60),
                            ('v2', 30),
                            ('v3', 10),
                            ('v4', 0)]:
        dns_identifier = 'myapp-{}'.format(ver)
        records[dns_identifier] = record(dns_identifier,
                                         percentage * PERCENT_RESOLUTION)

    rr.__iter__ = lambda x: iter(records.values())
    monkeypatch.setattr('senza.traffic.Route53.get_records',
                        MagicMock(return_value=rr))

    def change_rr_set(HostedZoneId, ChangeBatch):
        for change in ChangeBatch['Changes']:
            action = change['Action']
            rrset = change['ResourceRecordSet']
            if action == 'UPSERT':
                records[rrset['SetIdentifier']] = Route53Record.from_boto_dict(rrset)
            elif action == 'DELETE':
                records[rrset['SetIdentifier']].weight = 0

    boto_client['route53'].change_resource_record_sets = change_rr_set

    runner = CliRunner()

    common_opts = ['traffic', '--region=aa-fakeregion-1', 'myapp']

    def run(opts):
        result = runner.invoke(cli, common_opts + opts, catch_exceptions=False)
        assert 'Setting weights for myapp.zo.ne..' in result.output
        return result

    def weights():
        return [r.weight for r in records.values()]

    m_cfs = MagicMock()
    m_stacks = collections.defaultdict(MagicMock)

    def get_stack(name, region):
        assert region == 'aa-fakeregion-1'
        if name not in m_stacks:
            stack = m_stacks[name]
            resources = {
                'AppLoadBalancerMainDomain': {
                    'Type': 'AWS::Route53::RecordSet',
                    'Properties': {'Weight': 20,
                                   'Name': 'myapp.zo.ne.'}
                }
            }
            stack.template = {'Resources': resources}
        return m_stacks[name]

    m_cfs.get_by_stack_name = get_stack

    def get_weight(stack):
        resources = stack.template['Resources']
        lb = resources['AppLoadBalancerMainDomain']
        w = lb['Properties']['Weight']
        return w

    def update_weights(stacks):
        for key, value in stacks.items():
            w = get_weight(value)
            records[key].weight = w

    monkeypatch.setattr('senza.traffic.CloudFormationStack', m_cfs)

    with runner.isolated_filesystem():
        run(['v4', '100'])
        assert get_weight(m_stacks['myapp-v1']) == 0
        assert get_weight(m_stacks['myapp-v2']) == 0
        assert get_weight(m_stacks['myapp-v3']) == 0
        assert get_weight(m_stacks['myapp-v4']) == 200

        update_weights(m_stacks)
        run(['v3', '10'])
        assert get_weight(m_stacks['myapp-v1']) == 0
        assert get_weight(m_stacks['myapp-v2']) == 0
        assert get_weight(m_stacks['myapp-v3']) == 20
        assert get_weight(m_stacks['myapp-v4']) == 180

        update_weights(m_stacks)
        run(['v2', '0.5'])
        assert get_weight(m_stacks['myapp-v1']) == 0
        assert get_weight(m_stacks['myapp-v2']) == 1
        assert get_weight(m_stacks['myapp-v3']) == 20
        assert get_weight(m_stacks['myapp-v4']) == 179

        update_weights(m_stacks)
        run(['v1', '1'])
        assert get_weight(m_stacks['myapp-v1']) == 2
        assert get_weight(m_stacks['myapp-v2']) == 1
        assert get_weight(m_stacks['myapp-v3']) == 19
        assert get_weight(m_stacks['myapp-v4']) == 178

        update_weights(m_stacks)
        run(['v4', '95'])
        assert get_weight(m_stacks['myapp-v1']) == 1
        assert get_weight(m_stacks['myapp-v2']) == 1
        assert get_weight(m_stacks['myapp-v3']) == 13
        assert get_weight(m_stacks['myapp-v4']) == 185

        update_weights(m_stacks)
        run(['v4', '100'])
        assert get_weight(m_stacks['myapp-v1']) == 0
        assert get_weight(m_stacks['myapp-v2']) == 0
        assert get_weight(m_stacks['myapp-v3']) == 0
        assert get_weight(m_stacks['myapp-v4']) == 200

        update_weights(m_stacks)
        run(['v4', '10'])
        assert get_weight(m_stacks['myapp-v1']) == 0
        assert get_weight(m_stacks['myapp-v2']) == 0
        assert get_weight(m_stacks['myapp-v3']) == 0
        assert get_weight(m_stacks['myapp-v4']) == 200

        update_weights(m_stacks)
        run(['v4', '0'])
        assert get_weight(m_stacks['myapp-v1']) == 0
        assert get_weight(m_stacks['myapp-v2']) == 0
        assert get_weight(m_stacks['myapp-v3']) == 0
        assert get_weight(m_stacks['myapp-v4']) == 0

    # test not changed
    for stack in m_stacks.values():
        stack.update.side_effect = StackNotUpdated('abc')

    m_ok = MagicMock()
    monkeypatch.setattr('senza.traffic.ok', m_ok)

    with runner.isolated_filesystem():
        run(['v4', '100'])
        # TODO this now only checks for the correct result but it should actually check for the raw Route53 commands
        assert get_weight(m_stacks['myapp-v1']) == 0
        assert get_weight(m_stacks['myapp-v2']) == 0
        assert get_weight(m_stacks['myapp-v3']) == 0
        assert get_weight(m_stacks['myapp-v4']) == 200

    # test fallback
    m_cfs.get_by_stack_name = MagicMock(side_effect=StackNotFound('abc'))

    with runner.isolated_filesystem():
        run(['v4', '100'])
        assert weights() == [0, 0, 0, 200]

        run(['v3', '10'])
        assert weights() == [0, 0, 20, 180]

    # Test ELB Not found

    def get_stack_no_resources(name, region):
        assert region == 'aa-fakeregion-1'
        stack = MagicMock()
        resources = {}
        stack.template = {'Resources': resources}
        return stack

    m_cfs.get_by_stack_name = get_stack_no_resources

    with runner.isolated_filesystem():
        with pytest.raises(ELBNotFound):
            run(['v4', '100'])


def test_traffic_change_stack_in_progress(monkeypatch, boto_client):  # noqa: F811
    runner = CliRunner()
    target_stack_version = 'v1'

    def _run_for_stacks_states_changes(state_progress: List):
        stacks_state_progress_queue = collections.deque(state_progress)

        def _fake_progress_of_stack_changes(stack_refs, *args, **kwargs) -> List:
            if stacks_state_progress_queue:
                return [
                    SenzaStackSummary({'StackName': 'myapp',
                                       'StackStatus': stacks_state_progress_queue.popleft()})
                    for _ in stack_refs]
            else:
                return []

        monkeypatch.setattr('senza.aws.get_stacks', _fake_progress_of_stack_changes)

        with runner.isolated_filesystem():
            sub_command = ['traffic', '--region=aa-fakeregion-1', 'myapp', target_stack_version, '100', '-t', '200']
            return runner.invoke(cli, sub_command, catch_exceptions=False)

    mocked_change_version_traffic = MagicMock(name='mocked_change_version_traffic')
    monkeypatch.setattr('senza.cli.change_version_traffic', mocked_change_version_traffic)

    mocked_time_sleep = MagicMock(name='mocked_time_sleep')
    monkeypatch.setattr('senza.cli.time.sleep', mocked_time_sleep)

    @contextmanager
    def _reset_mocks_ctx():
        yield
        mocked_change_version_traffic.reset_mock()
        mocked_time_sleep.reset_mock()

    # test stack not found
    with _reset_mocks_ctx():
        result = _run_for_stacks_states_changes([])

        assert 'Stack not found!' in result.output
        mocked_change_version_traffic.assert_not_called()
        mocked_time_sleep.assert_not_called()

    # test stack in progress
    with _reset_mocks_ctx():
        result = _run_for_stacks_states_changes(['UPDATE_IN_PROGRESS', 'UPDATE_COMPLETE'])

        assert 'Waiting for stack myapp (UPDATE_IN_PROGRESS) to perform requested operation..' in result.output
        mocked_time_sleep.assert_called_once_with(5)
        mocked_change_version_traffic.assert_called_once_with(get_stack_refs(['myapp', 'v1'])[0], 100.0,
                                                              'aa-fakeregion-1')

    # the creation of the stack failed
    with _reset_mocks_ctx():
        result = _run_for_stacks_states_changes(['CREATE_IN_PROGRESS', 'CREATE_FAILED'])

        assert 'Waiting for stack myapp (CREATE_IN_PROGRESS) to perform requested operation..' in result.output
        mocked_time_sleep.assert_called_once_with(5)

    # test stack ready to change
    with _reset_mocks_ctx():
        _run_for_stacks_states_changes(['UPDATE_COMPLETE'])

        mocked_change_version_traffic.assert_called_once_with(get_stack_refs(['myapp', 'v1'])[0], 100.0,
                                                              'aa-fakeregion-1')
        mocked_time_sleep.assert_not_called()

    # test target stack is ready, but related ones are not, should wait
    with _reset_mocks_ctx():
        _run_for_stacks_states_changes(['CREATE_IN_PROGRESS', 'CREATE_COMPLETE'])

        mocked_change_version_traffic.assert_called_once_with(get_stack_refs(['myapp', 'v1'])[0], 100.0,
                                                              'aa-fakeregion-1')
        mocked_time_sleep.assert_called_once_with(5)


def test_AccountArguments(monkeypatch):
    senza.traffic.DNS_ZONE_CACHE = {}
    senza_aws = MagicMock()
    senza_aws.get_account_alias.return_value = 'test-cli'
    senza_aws.get_account_id.return_value = '123456'
    boto3 = MagicMock()
    boto3.list_hosted_zones.return_value = {'HostedZones': [HOSTED_ZONE_EXAMPLE_NET]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    monkeypatch.setattr('senza.definitions.get_account_alias', MagicMock(return_value='test-cli'))
    monkeypatch.setattr('senza.definitions.get_account_id', MagicMock(return_value='98741256325'))

    test = AccountArguments('test-region')

    assert test.Region == 'test-region'
    assert test.AccountAlias == 'test-cli'
    assert test.AccountID == '98741256325'
    assert test.Domain == 'example.net'
    assert test.TeamID == 'cli'


def test_patch(monkeypatch):
    boto3 = MagicMock()
    boto3.list_stacks.return_value = {'StackSummaries': [{'StackName': 'myapp-1',
                                                          'CreationTime': '2016-06-14'}]}
    boto3.describe_stack_resources.return_value = {'StackResources':
                                                       [{'ResourceType': 'AWS::AutoScaling::AutoScalingGroup',
                                                         'PhysicalResourceId': 'myasg',
                                                         'StackName': 'myapp-1'}]}
    group = {'AutoScalingGroupName': 'myasg'}
    boto3.describe_auto_scaling_groups.return_value = {'AutoScalingGroups': [group]}
    image = MagicMock()
    image.id = 'latesttaupage-123'

    props = {}

    def patch_auto_scaling_group(group, region, properties):
        props.update(properties)

    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    monkeypatch.setattr('senza.stups.taupage.find_image', MagicMock(return_value=image))
    monkeypatch.setattr('senza.cli.patch_auto_scaling_group', patch_auto_scaling_group)
    runner = CliRunner()
    result = runner.invoke(cli, ['patch', 'myapp', '1', '--image=latest', '--region=aa-fakeregion-1'],
                           catch_exceptions=False)

    assert props['ImageId'] == 'latesttaupage-123'
    assert 'Patching Auto Scaling Group myasg' in result.output


def test_respawn(monkeypatch):
    boto3 = MagicMock()
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    boto3.list_stacks.return_value = {'StackSummaries': [{'StackName': 'myapp-1',
                                                          'CreationTime': '2016-06-14'}]}
    boto3.describe_stack_resources.return_value = {'StackResources': [
        {
            'ResourceType': 'AWS::AutoScaling::AutoScalingGroup',
            'PhysicalResourceId': 'myasg',
            'StackName': 'myapp-1'
        }]}
    monkeypatch.setattr('senza.respawn.respawn_auto_scaling_group', lambda *args, **kwargs: None)
    runner = CliRunner()
    runner.invoke(cli, ['respawn', 'myapp', '1', '--region=aa-fakeregion-1'],
                  catch_exceptions=False)


def test_respawn_elastigroup(monkeypatch):
    boto3 = MagicMock()
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    boto3.list_stacks.return_value = {'StackSummaries': [{'StackName': 'myapp-1',
                                                          'CreationTime': '2016-06-14'}]}

    elastigroup_id = 'myelasti'
    boto3.describe_stack_resources.return_value = {'StackResources':
                                                       [{'ResourceType': ELASTIGROUP_RESOURCE_TYPE,
                                                         'PhysicalResourceId': elastigroup_id,
                                                         'StackName': 'myapp-1'}]}

    test = {'success': False}

    def verification(*args):
        test['success'] = True

    monkeypatch.setattr('senza.respawn.respawn_elastigroup', verification)
    runner = CliRunner()
    runner.invoke(cli, ['respawn', 'myapp', '1', '--region=aa-fakeregion-1'],
                  catch_exceptions=False)

    assert test['success']


def test_scale(monkeypatch):
    boto3 = MagicMock()
    boto3.list_stacks.return_value = {'StackSummaries': [{'StackName': 'myapp-1',
                                                          'CreationTime': '2016-06-14'}]}
    boto3.describe_stack_resources.return_value = {'StackResources': [
        {'ResourceType': 'AWS::AutoScaling::AutoScalingGroup',
         'PhysicalResourceId': 'myasg',
         'StackName': 'myapp-1'}]}
    # NOTE: we are using invalid MinSize (< capacity) here to get one more line covered ;-)
    group = {'AutoScalingGroupName': 'myasg', 'DesiredCapacity': 1, 'MinSize': 3, 'MaxSize': 1}
    boto3.describe_auto_scaling_groups.return_value = {'AutoScalingGroups': [group]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    runner = CliRunner()
    result = runner.invoke(cli, ['scale', 'myapp', '1', '2', '--region=aa-fakeregion-1'],
                           catch_exceptions=False)
    assert 'Scaling myasg from 1 to 2 instances' in result.output


def test_scale_elastigroup(monkeypatch):
    spotinst_account_id = 'fakeactid'
    elastigroup_id = 'myelasti'
    boto3 = MagicMock()
    boto3.list_stacks.return_value = {'StackSummaries': [{'StackName': 'myapp-1',
                                                          'CreationTime': '2016-06-14'}]}
    boto3.describe_stack_resources.return_value = {'StackResources':
                                                       [{'ResourceType': ELASTIGROUP_RESOURCE_TYPE,
                                                         'PhysicalResourceId': elastigroup_id,
                                                         'StackName': 'myapp-1'}]}
    boto3.get_template.return_value = {
        'TemplateBody': {
            'Mappings': {'Senza': {'Info': {}}},
            'Resources': {
                'AppServerConfig': {
                    'Type': ELASTIGROUP_RESOURCE_TYPE,
                    'Properties': {
                        'accountId': spotinst_account_id,
                        'accessToken': 'faketoken',
                    }
                }
            }
        }
    }

    group = [{
        'capacity': {
            'minimum': 1,
            'maximum': 2,
            'target': 1,
            'unit': 'instance'
        }
    }]
    get_elastigroup = MagicMock()
    get_elastigroup.return_value = group

    update = [{
        'capacity': {
            'minimum': 1,
            'maximum': 3,
            'target': 3,
            'unit': 'instance'
        }
    }]
    update_capacity = MagicMock()
    update_capacity.return_value = update

    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    monkeypatch.setattr('senza.spotinst.components.elastigroup_api.get_elastigroup', get_elastigroup)
    monkeypatch.setattr('senza.spotinst.components.elastigroup_api.update_capacity', update_capacity)

    runner = CliRunner()
    result = runner.invoke(cli, ['scale', 'myapp', '1', '3', '--region=aa-fakeregion-1'],
                           catch_exceptions=False)
    assert 'Scaling ElastiGroup myapp-1 (ID: myelasti) from 1 to 3 instances' in result.output


def test_scale_with_confirm(monkeypatch):
    boto3 = MagicMock()
    boto3.list_stacks.return_value = {'StackSummaries': [
        {'StackName': 'myapp-1', 'CreationTime': '2016-06-14'},
        {'StackName': 'myapp-1', 'CreationTime': '2016-06-15'},
        {'StackName': 'myapp-1', 'CreationTime': '2016-06-16'},
    ]}
    boto3.describe_stack_resources.return_value = {'StackResources':
                                                       [{'ResourceType': 'AWS::AutoScaling::AutoScalingGroup',
                                                         'PhysicalResourceId': 'myasg'}]}
    group = {'AutoScalingGroupName': 'myasg', 'DesiredCapacity': 1, 'MinSize': 3, 'MaxSize': 1}
    boto3.describe_auto_scaling_groups.return_value = {'AutoScalingGroups': [group]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    runner = CliRunner()
    result = runner.invoke(cli, ['scale', 'myapp', '2', '--region=aa-fakeregion-1'],
                           catch_exceptions=False)
    assert 'Number of stacks to be scaled - 3. Do you want to continue?' in result.output


def test_scale_with_force_confirm(monkeypatch):
    boto3 = MagicMock()
    boto3.list_stacks.return_value = {'StackSummaries': [
        {'StackName': 'myapp-1', 'CreationTime': '2016-06-14'},
        {'StackName': 'myapp-1', 'CreationTime': '2016-06-15'},
        {'StackName': 'myapp-1', 'CreationTime': '2016-06-16'},
    ]}
    boto3.describe_stack_resources.return_value = {'StackResources':
                                                       [{'ResourceType': 'AWS::AutoScaling::AutoScalingGroup',
                                                         'PhysicalResourceId': 'myasg',
                                                         'StackName': 'myapp-1'}]}
    group = {'AutoScalingGroupName': 'myasg', 'DesiredCapacity': 1, 'MinSize': 3, 'MaxSize': 1}
    boto3.describe_auto_scaling_groups.return_value = {'AutoScalingGroups': [group]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    runner = CliRunner()
    result = runner.invoke(cli, ['scale', 'myapp', '2', '--region=aa-fakeregion-1', '--force'],
                           catch_exceptions=False)
    assert 'Scaling myasg from 1 to 2 instances' in result.output

def test_scale_with_overwriting_zero_minsize(monkeypatch):
    boto3 = MagicMock()
    boto3.list_stacks.return_value = {'StackSummaries': [{'StackName': 'myapp-1',
                                                          'CreationTime': '2016-06-14'}]}
    boto3.describe_stack_resources.return_value = {'StackResources': [
      {'ResourceType': 'AWS::AutoScaling::AutoScalingGroup',
       'PhysicalResourceId': 'myasg',
       'StackName': 'myapp-1'}]}
    group = {'AutoScalingGroupName': 'myasg', 'DesiredCapacity': 0, 'MinSize': 0, 'MaxSize': 8}
    boto3.describe_auto_scaling_groups.return_value = {'AutoScalingGroups': [group]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    runner = CliRunner()
    result = runner.invoke(cli, ['scale', 'myapp', '1', '2', '--region=aa-fakeregion-1', '--min-size', '1'],
                           catch_exceptions=False)
    assert 'Scaling myasg from 0 to 2 instances' in result.output

def test_scale_desired_capacity_smaller_than_min_size(monkeypatch):
    boto3 = MagicMock()
    boto3.list_stacks.return_value = {'StackSummaries': [{'StackName': 'myapp-1',
                                                          'CreationTime': '2016-06-14'}]}
    boto3.describe_stack_resources.return_value = {'StackResources': [
      {'ResourceType': 'AWS::AutoScaling::AutoScalingGroup',
       'PhysicalResourceId': 'myasg',
       'StackName': 'myapp-1'}]}
    group = {'AutoScalingGroupName': 'myasg', 'DesiredCapacity': 0, 'MinSize': 0, 'MaxSize': 8}
    boto3.describe_auto_scaling_groups.return_value = {'AutoScalingGroups': [group]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    runner = CliRunner()
    result = runner.invoke(cli, ['scale', 'myapp', '1', '2', '--region=aa-fakeregion-1', '--min-size', '4'],
                           catch_exceptions=False)
    assert 'Desired capacity must be bigger than specified min_size value' in result.output

def test_scale_with_min_size_zero_without_specifying_it(monkeypatch):
    boto3 = MagicMock()
    boto3.list_stacks.return_value = {'StackSummaries': [{'StackName': 'myapp-1',
                                                          'CreationTime': '2016-06-14'}]}
    boto3.describe_stack_resources.return_value = {'StackResources': [
      {'ResourceType': 'AWS::AutoScaling::AutoScalingGroup',
       'PhysicalResourceId': 'myasg',
       'StackName': 'myapp-1'}]}
    group = {'AutoScalingGroupName': 'myasg', 'DesiredCapacity': 0, 'MinSize': 0, 'MaxSize': 8}
    boto3.describe_auto_scaling_groups.return_value = {'AutoScalingGroups': [group]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    runner = CliRunner()
    result = runner.invoke(cli, ['scale', 'myapp', '1', '2', '--region=aa-fakeregion-1'],
                           catch_exceptions=False)
    assert 'MinSize was set to 0 previously' in result.output

def test_wait(monkeypatch):
    cf = MagicMock()
    stack1 = {'StackName': 'test-1',
              'CreationTime': datetime.datetime.utcnow(),
              'StackStatus': 'UPDATE_COMPLETE'}
    stack2 = {'StackName': 'test-2',
              'CreationTime': datetime.datetime.utcnow(),
              'StackStatus': 'CREATE_COMPLETE'}
    stack3 = {'StackName': 'test-3',
              'CreationTime': datetime.datetime.utcnow(),
              'StackStatus': 'DELETE_COMPLETE'}

    cf.list_stacks.return_value = {'StackSummaries': [stack1, stack2, stack3]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=cf))

    def my_resource(rtype, *args):
        return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'cloudformation':
            return cf
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)

    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(cli,
                               ['wait', 'test', '1', '--region=aa-fakeregion-1'],
                               catch_exceptions=False)
        assert "OK: Stack(s) test-1 updated successfully" in result.output

        result = runner.invoke(cli,
                               ['wait', 'test', '2',
                                '--region=aa-fakeregion-1'],
                               catch_exceptions=False)
        assert "OK: Stack(s) test-2 created successfully" in result.output

        result = runner.invoke(cli,
                               ['wait', '--deletion', 'test', '3',
                                '--region=aa-fakeregion-1'],
                               catch_exceptions=False)
        assert "OK: Stack(s) test-3 deleted successfully" in result.output

        # test creating/updating several stacks at once.
        result = runner.invoke(cli,
                               ['wait', 'test', '1', 'test', '2',
                                '--region=aa-fakeregion-1'],
                               input='n\n',
                               catch_exceptions=False)
        assert "created" in result.output
        assert "updated" in result.output


def test_wait_in_progress(monkeypatch):
    cf = MagicMock()
    stack1 = {'StackName': 'test-1',
              'CreationTime': datetime.datetime.utcnow(),
              'StackStatus': 'CREATE_IN_PROGRESS'}

    cf.list_stacks.return_value = {'StackSummaries': [stack1]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=cf))

    def my_resource(rtype, *args):
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('time.sleep', MagicMock())

    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(cli,
                               ['wait', 'test', '1', '--region=aa-fakeregion-1', '--timeout=1'],
                               catch_exceptions=False)
        assert "Waiting up to 1 more secs for stack test-1 (CREATE_IN_PROGRESS).." in result.output
        assert 'Aborted!' in result.output
        assert 1 == result.exit_code


def test_wait_failure(monkeypatch):
    cf = MagicMock()
    stack1 = {'StackName': 'test-1',
              'CreationTime': datetime.datetime.utcnow(),
              'StackStatus': 'ROLLBACK_COMPLETE'}

    cf.list_stacks.return_value = {'StackSummaries': [stack1]}
    cf.describe_stack_events.return_value = {'StackEvents':
                                                 [{'Timestamp': 0,
                                                   'ResourceStatus': 'FAIL',
                                                   'ResourceStatusReason': 'myreason',
                                                   'LogicalResourceId': 'foo'}]}
    monkeypatch.setattr('boto3.client', MagicMock(return_value=cf))

    def my_resource(rtype, *args):
        return MagicMock()

    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('time.sleep', MagicMock())

    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(cli,
                               ['wait', 'test', '1', '--region=aa-fakeregion-1'],
                               catch_exceptions=False)
        assert 'ERROR: foo FAIL: myreason' in result.output
        assert 'ERROR: Stack test-1 has status ROLLBACK_COMPLETE' in result.output
        assert 1 == result.exit_code


def test_key_val_param():
    assert KeyValParamType().convert(('a', 'b'), None, None) == ('a', 'b')


def test_account_arguments():
    test = AccountArguments('blubber')
    assert test.Region == 'blubber'


def test_get_stack_reference(monkeypatch):
    fb_none = StackReference(name='foobar-stack', version=None)
    fb_v1 = StackReference(name='foobar-stack', version='v1')
    fb_v2 = StackReference(name='foobar-stack', version='v2')
    fb_v99 = StackReference(name='foobar-stack', version='v99')
    os_none = StackReference(name='other-stack', version=None)

    assert get_stack_refs(['foobar-stack']) == [fb_none]

    assert get_stack_refs(['foobar-stack', 'v1']) == [fb_v1]

    assert get_stack_refs(['foobar-stack', 'v1',
                           'other-stack']) == [fb_v1, os_none]
    assert get_stack_refs(['foobar-stack', 'v1', 'v2', 'v99',
                           'other-stack']) == [fb_v1, fb_v2, fb_v99,
                                               os_none]

    monkeypatch.setattr('builtins.open',
                        mock_open(read_data='{"SenzaInfo": '
                                            '{"StackName": "foobar-stack"}}'))
    assert get_stack_refs(['test.yaml']) == [fb_none]

    monkeypatch.setattr('builtins.open',
                        mock_open(read_data='invalid: true'))
    with pytest.raises(InvalidDefinition) as exc_info1:
        get_stack_refs(['test.yaml'])

    assert (str(exc_info1.value) == "test.yaml is not a valid "
                                    "senza definition: SenzaInfo is missing "
                                    "or invalid")

    monkeypatch.setattr('builtins.open',
                        mock_open(read_data='{"SenzaInfo": 42}'))
    with pytest.raises(InvalidDefinition) as exc_info2:
        get_stack_refs(['test.yaml'])

    assert (str(exc_info2.value) == "test.yaml is not a valid "
                                    "senza definition: Invalid SenzaInfo")

    monkeypatch.setattr('builtins.open',
                        mock_open(read_data='"badxml'))

    with pytest.raises(InvalidDefinition) as exc_info3:
        get_stack_refs(['test.yaml'])

    assert "while scanning a quoted scalar" in str(exc_info3.value)


def test_all_with_version():
    assert not all_with_version([StackReference(name='foobar-stack',
                                                version='1'),
                                 StackReference(name='other-stack',
                                                version=None)])

    assert all_with_version([StackReference(name='foobar-stack', version='1'),
                             StackReference(name='other-stack',
                                            version='v23')])

    assert all_with_version([StackReference(name='foobar-stack',
                                            version='1')])

    assert not all_with_version([StackReference(name='other-stack',
                                                version=None)])


def test_is_ip_address():
    assert not is_ip_address("YOLO")
    assert is_ip_address('127.0.0.1')


def test_get_console_line_style():
    assert get_console_line_style('foo') == {}

    assert get_console_line_style('ERROR:')['fg'] == 'red'

    assert get_console_line_style('WARNING:')['fg'] == 'yellow'

    assert get_console_line_style('SUCCESS:')['fg'] == 'green'

    assert get_console_line_style('INFO:')['bold']


def test_failure_event():
    assert not failure_event({})

    assert failure_event({'ResourceStatusReason': 'foo',
                          'ResourceStatus': 'FAIL'})


def test_status_main_dns(monkeypatch, disable_version_check):  # noqa: F811
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
        elif rtype == 'cloudformation':
            cf = MagicMock()
            version_domain = MagicMock()
            version_domain.logical_id = 'VersionDomain'
            version_domain.resource_type = 'AWS::Route53::RecordSet'
            version_domain.physical_resource_id = 'test-1.example.org'
            main_domain = MagicMock()
            main_domain.logical_id = 'MainDomain'
            main_domain.resource_type = 'AWS::Route53::RecordSet'
            main_domain.physical_resource_id = 'test.example.org'
            cf.Stack.return_value.resource_summaries.all.return_value = [version_domain, main_domain]
            return cf
        return MagicMock()

    def my_client(rtype, *args):
        if rtype == 'cloudformation':
            cf = MagicMock()
            cf.list_stacks.return_value = {'StackSummaries': [{'StackName': 'test-1',
                                                               'CreationTime': '2016-06-14'}]}
            return cf
        return MagicMock()

    def resolve_to_ip_addresses(dns_name):
        return {'test-1.example.org': {'1.2.3.4', '5.6.7.8'}, 'test.example.org': {'5.6.7.8'}}.get(dns_name)

    monkeypatch.setattr('boto3.resource', my_resource)
    monkeypatch.setattr('boto3.client', my_client)
    monkeypatch.setattr('senza.cli.resolve_to_ip_addresses', resolve_to_ip_addresses)

    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ['status', 'test', '--region=aa-fakeregion-1', '1', '--output=json'],
                               catch_exceptions=False)

    data = json.loads(result.output.strip())
    assert data[0]['main_dns'] is True


def test_traffic_fallback_route53api(monkeypatch, boto_client, boto_resource):  # noqa: F811
    stacks = [
        StackVersion('myapp', 'v1', ['myapp.zo.ne'],
                     ['some-lb.eu-central-1.elb.amazonaws.com'], ['some-arn']),
        StackVersion('myapp', 'v2', ['myapp.zo.ne'],
                     ['another-elb.eu-central-1.elb.amazonaws.com'], ['some-arn']),
    ]
    monkeypatch.setattr('senza.traffic.get_stack_versions',
                        MagicMock(return_value=stacks))

    referenced_stacks = [
        SenzaStackSummary({'StackName': s.name, 'StackStatus': 'UPDATE_COMPLETE'})
        for s in stacks
    ]
    monkeypatch.setattr('senza.cli.get_stacks', MagicMock(name="fake_get_stacks", return_value=referenced_stacks))

    def _record(dns_identifier, weight):
        return Route53Record(name='myapp.zo.ne.',
                             type=RecordType.A,
                             weight=weight,
                             set_identifier=dns_identifier)

    rr = MagicMock()
    records = collections.OrderedDict()

    # scenario: v1 DNS record was manually updated to 100% (not via CF)
    for ver, percentage in [('v1', 100),
                            ('v2', 0)]:
        dns_identifier = 'myapp-{}'.format(ver)
        records[dns_identifier] = _record(dns_identifier,
                                          percentage * PERCENT_RESOLUTION)

    rr.__iter__ = lambda x: iter(records.values())
    monkeypatch.setattr('senza.traffic.Route53.get_records',
                        MagicMock(return_value=rr))

    def _change_rr_set(HostedZoneId, ChangeBatch):
        for change in ChangeBatch['Changes']:
            action = change['Action']
            rrset = change['ResourceRecordSet']
            assert action == 'UPSERT'
            records[rrset['SetIdentifier']] = Route53Record.from_boto_dict(rrset)

    boto_client['route53'].change_resource_record_sets = _change_rr_set

    runner = CliRunner()

    common_opts = ['traffic', '--region=aa-fakeregion-1', 'myapp']

    def _run(opts):
        result = runner.invoke(cli, common_opts + opts, catch_exceptions=False)
        assert 'Setting weights for myapp.zo.ne..' in result.output
        return result

    m_cfs = MagicMock()
    m_stacks = collections.defaultdict(MagicMock)

    def _get_stack(name, region):
        if name not in m_stacks:
            stack = m_stacks[name]
            stack.template = {'Resources': {
                'MyMainDomain': {
                    'Type': 'AWS::Route53::RecordSet',
                    'Properties': {'Weight': 999,  # does not matter
                                   'Name': 'myapp.zo.ne.'}
                }
            }}
            if name == 'myapp-v1':
                # CF will say "no need to update" as v1 was not updated via CF
                stack.update.side_effect = StackNotUpdated('app-v1 record was manipulated through Route53 API')
        return m_stacks[name]

    m_cfs.get_by_stack_name = _get_stack

    def _get_weight(stack):
        return stack.template['Resources']['MyMainDomain']['Properties']['Weight']

    monkeypatch.setattr('senza.traffic.CloudFormationStack', m_cfs)

    with runner.isolated_filesystem():
        _run(['v2', '100'])
        # check that template resource weights were updated..
        assert _get_weight(m_stacks['myapp-v1']) == 0
        assert _get_weight(m_stacks['myapp-v2']) == 200
        # IMPORTANT: DNS record of v1 must have been updated!
        assert records['myapp-v1'].weight == 0
        # we won't check v2 as it was not manipulated (only via CF)


def test_create_cf_template_compact_json(monkeypatch):
    monkeypatch.setattr('boto3.client', MagicMock())
    definition = {'SenzaInfo': {'StackName': 'foo-compact-json'}}
    cf_template = create_cf_template(definition, 'aa-fakeregion-1', '1', [], False, None)
    # verify that we are using the "compressed" JSON format (no indentation, no extra whitespace)
    assert '"Senza":{"Info":' in cf_template['TemplateBody']
