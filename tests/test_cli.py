import datetime
import os
from click.testing import CliRunner
from mock import MagicMock
import yaml
from senza.cli import cli
import boto.exception


def test_invalid_definition():
    data = {}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123'], catch_exceptions=False)

    assert 'Error: Invalid value for "definition"' in result.output


def test_print_basic(monkeypatch):
    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: MagicMock())

    data = {'SenzaInfo': {'StackName': 'test'}, 'SenzaComponents': [{'Configuration': {'Type': 'Senza::Configuration',
                                                                                       'ServerSubnets': {
                                                                                       'eu-west-1': ['subnet-123']}}},
                                                                    {'AppServer': {
                                                                    'Type': 'Senza::TaupageAutoScalingGroup',
                                                                    'InstanceType': 't2.micro',
                                                                    'Image': 'AppImage',
                                                                    'TaupageConfig': {}}}]}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123', '1.0-SNAPSHOT'],
                               catch_exceptions=False)

    assert 'AWSTemplateFormatVersion' in result.output
    assert 'subnet-123' in result.output


def test_print_auto(monkeypatch):
    images = [MagicMock(name='Taupage-AMI-123', id='ami-123')]

    zone = MagicMock()
    zone.name = 'zo.ne'
    cert = {'server_certificate_name': 'zo-ne', 'arn': 'arn:aws:123'}
    cert_response = {'list_server_certificates_response': {'list_server_certificates_result': {'server_certificate_metadata_list': [
        cert
    ]}}}

    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.vpc.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock(list_server_certs=lambda: cert_response))
    monkeypatch.setattr('boto.route53.connect_to_region', lambda x: MagicMock(get_zones=lambda: [zone]))
    monkeypatch.setattr('boto.ec2.connect_to_region', lambda x: MagicMock(get_all_images=lambda filters: images))

    data = {'SenzaInfo': {'StackName': 'test',
                          'OperatorTopicId': 'mytopic'},
            'SenzaComponents': [{'Configuration': {'Type': 'Senza::StupsAutoConfiguration'}},
                                {'AppServer': {'Type': 'Senza::TaupageAutoScalingGroup',
                                               'InstanceType': 't2.micro',
                                               'TaupageConfig': {},
                                               'SecurityGroups': ['app-sg']}},
                                {'AppLoadBalancer': {'Type': 'Senza::WeightedDnsElasticLoadBalancer',
                                                     'HTTPPort': 8080,
                                                     'SecurityGroups': ['app-sg']}}]}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123', '1.0-SNAPSHOT'],
                               catch_exceptions=False)

    assert 'AWSTemplateFormatVersion' in result.output
    assert 'subnet-123' in result.output


def test_init(monkeypatch):
    monkeypatch.setattr('boto.ec2.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.vpc.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ['init', 'myapp.yaml', '--region=myregion', '-v', 'test=123'],
                               catch_exceptions=False, input='1\nsdf\nsdf\n8080\n/\n')
        assert os.path.exists('myapp.yaml')
        with open('myapp.yaml') as fd:
            generated_definition = yaml.safe_load(fd)

    assert 'Generating Senza definition file myapp.yaml.. OK' in result.output
    assert generated_definition['SenzaInfo']['StackName'] == 'sdf'

def test_instances(monkeypatch):
    stack = MagicMock()
    inst = MagicMock()
    monkeypatch.setattr('boto.ec2.connect_to_region', lambda x: MagicMock(get_only_instances=lambda filters: [inst]))
    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: MagicMock(describe_stacks=lambda x: [stack]))

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['instances', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)

    assert 'Launched' in result.output


def test_resources(monkeypatch):
    res = MagicMock(timestamp=datetime.datetime.now(), logical_resource_id='MyTestResource', resource_type='AWS::abc')
    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: MagicMock(describe_stack_resources=lambda x: [res]))

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['resources', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)

    assert 'MyTestResource' in result.output


def test_events(monkeypatch):
    evt = MagicMock(timestamp=datetime.datetime.now(), logical_resource_id='MyTestEventRes', resource_type='foobar')
    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: MagicMock(describe_stack_events=lambda x: [evt]))

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['events', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)

    assert 'MyTestEventRes' in result.output


def test_list(monkeypatch):
    stack = MagicMock(stack_name='test-1', creation_time=datetime.datetime.now())
    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: MagicMock(list_stacks=lambda stack_status_filters: [stack]))

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['list', 'myapp.yaml', '--region=myregion'],
                               catch_exceptions=False)

    assert 'test-1' in result.output


def test_delete(monkeypatch):
    cf = MagicMock()
    stack = MagicMock(stack_name='test-1')
    cf.list_stacks.return_value = [stack]
    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: cf)

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['delete', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)

    assert 'OK' in result.output

def test_create(monkeypatch):
    cf = MagicMock()
    monkeypatch.setattr('boto.cloudformation.connect_to_region', MagicMock(return_value=cf))

    runner = CliRunner()

    data = {'SenzaInfo': {
        'StackName': 'test', 'Parameters': [{'MyParam': {'Type': 'String'}}]},
            'SenzaComponents': [{'Config': {'Type': 'Senza::Configuration'}}]}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['create', 'myapp.yaml', '--region=myregion', '1', 'my-param-value'],
                               catch_exceptions=False)
        assert 'OK' in result.output

        cf.create_stack.side_effect=boto.exception.BotoServerError('sdf', 'already exists',
                                                                   {'Error': {'Code': 'AlreadyExistsException'}})
        result = runner.invoke(cli, ['create', 'myapp.yaml', '--region=myregion', '1', 'my-param-value'],
                               catch_exceptions=True)
        assert 'Stack test-1 already exists' in result.output
