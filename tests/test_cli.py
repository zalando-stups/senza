import os
from click.testing import CliRunner
from mock import MagicMock
import yaml
from senza.cli import cli


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

    data = {'SenzaInfo': {'StackName': 'test'},
            'SenzaComponents': [{'Configuration': {'Type': 'Senza::StupsAutoConfiguration'}},
                                {'AppServer': {'Type': 'Senza::TaupageAutoScalingGroup',
                                               'InstanceType': 't2.micro',
                                               'TaupageConfig': {}}},
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
    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ['init', '--template=webapp', 'myapp.yaml', '--region=myregion'],
                               catch_exceptions=False, input='sdf\nsdf\n8080\n/\n')
        assert os.path.exists('myapp.yaml')
        with open('myapp.yaml') as fd:
            generated_definition = yaml.safe_load(fd)

    assert 'Generating Senza definition file myapp.yaml.. OK' in result.output
    assert generated_definition['SenzaInfo']['StackName'] == 'sdf'
