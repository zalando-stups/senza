import datetime
import os
from click.testing import CliRunner
import collections
from unittest.mock import MagicMock, Mock
import yaml
from senza.cli import cli, handle_exceptions
import boto.exception
from senza.traffic import PERCENT_RESOLUTION, StackVersion


def test_invalid_definition():
    data = {}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123'], catch_exceptions=False)

    assert 'Error: Invalid value for "definition"' in result.output


def test_version():
    runner = CliRunner()
    result = runner.invoke(cli, ['--version'])
    assert result.output.startswith('Senza ')


def test_missing_credentials(capsys):
    func = MagicMock(side_effect=boto.exception.NoAuthHandlerFound())

    try:
        handle_exceptions(func)()
    except SystemExit:
        pass

    out, err = capsys.readouterr()
    assert 'No AWS credentials found.' in err


def test_expired_credentials(capsys):
    func = MagicMock(side_effect=boto.exception.BotoServerError(403, 'X',
                     {'message': '**Security Token included in the Request is expired**'}))

    try:
        handle_exceptions(func)()
    except SystemExit:
        pass

    out, err = capsys.readouterr()

    assert 'AWS credentials have expired.' in err


def test_print_basic(monkeypatch):
    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

    data = {'SenzaInfo': {'StackName': 'test'}, 'SenzaComponents': [{'Configuration': {'Type': 'Senza::Configuration',
                                                                                       'ServerSubnets': {
                                                                                           'eu-west-1': [
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
    sg = MagicMock()
    sg.name = 'app-master-mind'
    sg.id = 'sg-007'

    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.ec2.connect_to_region', lambda x: MagicMock(get_all_security_groups=lambda: [sg]))
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())
    data = {'SenzaInfo': {'StackName': 'test',
                          'Parameters': [{'ApplicationId': {'Description': 'Application ID from kio'}}]},
            'SenzaComponents': [{'Configuration': {'ServerSubnets': {'eu-west-1': ['subnet-123']},
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
    sg = MagicMock()
    sg.name = 'app-master-mind'
    sg.id = 'sg-007'

    boto3 = MagicMock()
    boto3.get_user.return_value = {'User': {'Arn': 'arn:aws:iam::0123456789:user/admin'}}
    boto3.list_account_aliases.return_value = {'AccountAliases': ['org-dummy']}

    monkeypatch.setattr('boto3.client', MagicMock(return_value=boto3))
    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.ec2.connect_to_region', lambda x: MagicMock(get_all_security_groups=lambda: [sg]))
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())
    data = {'SenzaComponents': [{'Configuration': {'ServerSubnets': {'eu-west-1': ['subnet-123']},
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

        result = runner.invoke(cli, ['print', 'myapp.yaml', '--region=myregion', '123', 'master-mind'],
                               catch_exceptions=False)
    assert 'test-myregion' in result.output
    assert 'AppImage-dummy-0123456789' in result.output


def test_print_auto(monkeypatch):
    images = [MagicMock(name='Taupage-AMI-123', id='ami-123')]

    zone = MagicMock()
    zone.name = 'zo.ne'
    cert = {'server_certificate_name': 'zo-ne', 'arn': 'arn:aws:123'}
    cert_response = {
        'list_server_certificates_response': {'list_server_certificates_result': {'server_certificate_metadata_list': [
            cert
        ]}}}

    sg = MagicMock()
    sg.name = 'app-sg'
    sg.id = 'sg-007'

    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.vpc.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock(list_server_certs=lambda: cert_response))
    monkeypatch.setattr('boto.route53.connect_to_region', lambda x: MagicMock(get_zones=lambda: [zone]))
    monkeypatch.setattr('boto.ec2.connect_to_region', lambda x: MagicMock(get_all_images=lambda filters: images,
                                                                          get_all_security_groups=lambda: [sg]))

    sns = MagicMock()
    topic = {'TopicArn': 'arn:123:mytopic'}
    sns.get_all_topics.return_value = {'ListTopicsResponse': {'ListTopicsResult': {'Topics': [topic]}}}
    monkeypatch.setattr('boto.sns.connect_to_region', MagicMock(return_value=sns))

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

    assert 'AWSTemplateFormatVersion' in result.output
    assert 'subnet-123' in result.output
    assert 'source: foo/bar:1.0-SNAPSHOT' in result.output
    assert '"HealthCheckType": "ELB"' in result.output


def test_dump(monkeypatch):
    stack = MagicMock(stack_name='mystack-1')
    cf = MagicMock()
    cf.list_stacks.return_value = [stack]
    cf.get_template.return_value = {'GetTemplateResponse': {'GetTemplateResult': {'TemplateBody': '{"foo": "bar"}'}}}
    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: cf)
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ['dump', 'mystack', '--region=myregion'],
                               catch_exceptions=False)

        assert '{"foo": "bar"}' == result.output.rstrip()

        result = runner.invoke(cli, ['dump', 'mystack', '--region=myregion', '-o', 'yaml'],
                               catch_exceptions=False)

        assert 'foo: bar' == result.output.rstrip()


def test_init(monkeypatch):
    monkeypatch.setattr('boto.ec2.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.vpc.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

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
    monkeypatch.setattr('boto.ec2.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.vpc.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

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
    stack = MagicMock(stack_name='test-1')
    inst = MagicMock()
    monkeypatch.setattr('boto.ec2.connect_to_region', lambda x: MagicMock(get_only_instances=lambda filters: [inst]))
    monkeypatch.setattr('boto.cloudformation.connect_to_region',
                        lambda x: MagicMock(list_stacks=lambda stack_status_filters: [stack]))
    monkeypatch.setattr('boto.ec2.elb.connect_to_region',
                        lambda x: MagicMock(describe_instance_health=lambda stack: []))
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['instances', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)

    assert 'Launched' in result.output


def test_console(monkeypatch):
    stack = MagicMock(stack_name='test-1')
    inst = MagicMock()
    inst.tags = {'aws:cloudformation:stack-name': 'test-1'}
    ec2 = MagicMock()
    ec2.get_only_instances.return_value = [inst]
    ec2.get_console_output.return_value.output = b'**MAGIC-CONSOLE-OUTPUT**'
    monkeypatch.setattr('boto.ec2.connect_to_region', lambda x: ec2)
    monkeypatch.setattr('boto.cloudformation.connect_to_region',
                        lambda x: MagicMock(list_stacks=lambda stack_status_filters: [stack]))
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['console', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)

        assert '**MAGIC-CONSOLE-OUTPUT**' in result.output

        result = runner.invoke(cli, ['console', 'foobar', '--region=myregion'],
                               catch_exceptions=False)
        assert '' == result.output

        result = runner.invoke(cli, ['console', '172.31.1.2', '--region=myregion'],
                               catch_exceptions=False)
        assert '**MAGIC-CONSOLE-OUTPUT**' in result.output

        result = runner.invoke(cli, ['console', 'i-123', '--region=myregion'],
                               catch_exceptions=False)
        assert '**MAGIC-CONSOLE-OUTPUT**' in result.output


def test_status(monkeypatch):
    stack = MagicMock(stack_name='test-1')
    inst = MagicMock()
    monkeypatch.setattr('boto.ec2.connect_to_region', lambda x: MagicMock(get_only_instances=lambda filters: [inst]))
    monkeypatch.setattr('boto.cloudformation.connect_to_region',
                        lambda x: MagicMock(list_stacks=lambda stack_status_filters: [stack]))
    monkeypatch.setattr('boto.ec2.elb.connect_to_region',
                        lambda x: MagicMock(describe_instance_health=lambda stack: []))
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['status', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)

    assert 'Running' in result.output


def test_resources(monkeypatch):
    stack = MagicMock(stack_name='test-1', creation_time=datetime.datetime.now())
    res = MagicMock(timestamp=datetime.datetime.now(), logical_resource_id='MyTestResource', resource_type='AWS::abc')
    monkeypatch.setattr('boto.cloudformation.connect_to_region',
                        lambda x: MagicMock(describe_stack_resources=lambda x: [res],
                                            list_stacks=lambda stack_status_filters: [stack]))
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['resources', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)

    assert 'MyTestResource' in result.output


def test_domains(monkeypatch):
    stack = MagicMock(stack_name='test-1', creation_time=datetime.datetime.now())
    res = MagicMock(timestamp=datetime.datetime.now(), logical_resource_id='MyTestResource',
                    physical_resource_id='mydomain.example.org',
                    resource_type='AWS::Route53::RecordSet')
    route53 = MagicMock()
    route53.get_zone.return_value.get_records.return_value = [MagicMock()]
    monkeypatch.setattr('boto.cloudformation.connect_to_region',
                        lambda x: MagicMock(describe_stack_resources=lambda x: [res],
                                            list_stacks=lambda stack_status_filters: [stack]))
    monkeypatch.setattr('boto.route53.connect_to_region', lambda x: route53)
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['domains', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)

    assert 'mydomain.example.org' in result.output


def test_events(monkeypatch):
    stack = MagicMock(stack_name='test-1', creation_time=datetime.datetime.now())
    evt = MagicMock(timestamp=datetime.datetime.now(), logical_resource_id='MyTestEventRes', resource_type='foobar')
    monkeypatch.setattr('boto.cloudformation.connect_to_region',
                        lambda x: MagicMock(describe_stack_events=lambda x: [evt],
                                            list_stacks=lambda stack_status_filters: [stack]))
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['events', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)

    assert 'MyTestEventRes' in result.output


def test_list(monkeypatch):
    stack = MagicMock(stack_name='test-stack-1', creation_time=datetime.datetime.now())
    monkeypatch.setattr('boto.cloudformation.connect_to_region',
                        lambda x: MagicMock(list_stacks=lambda stack_status_filters: [stack]))
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test-stack'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['list', 'myapp.yaml', '--region=myregion'],
                               catch_exceptions=False)

    assert 'test-stack' in result.output


def test_images(monkeypatch):
    image = MagicMock()
    image.id = 'ami-123'
    image.name = 'BrandNewImage'
    image.creationDate = datetime.datetime.utcnow().isoformat('T') + 'Z'

    old_image_still_used = MagicMock()
    old_image_still_used.id = 'ami-456'
    old_image_still_used.name = 'OldImage'
    old_image_still_used.creationDate = (datetime.datetime.utcnow() - datetime.timedelta(days=30)).isoformat('T') + 'Z'

    instance = MagicMock()
    instance.id = 'i-777'
    instance.image_id = 'ami-456'
    instance.tags = {'aws:cloudformation:stack-name': 'mystack'}

    ec2 = MagicMock()
    ec2.get_all_images.return_value = [image, old_image_still_used]
    ec2.get_only_instances.return_value = [instance]
    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: MagicMock())
    monkeypatch.setattr('boto.ec2.connect_to_region', lambda x: ec2)
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

    runner = CliRunner()

    with runner.isolated_filesystem():
        result = runner.invoke(cli, ['images', '--region=myregion'], catch_exceptions=False)

    assert 'ami-123' in result.output
    assert 'ami-456' in result.output
    assert 'mystack' in result.output


def test_delete(monkeypatch):
    cf = MagicMock()
    stack = MagicMock(stack_name='test-1')
    cf.list_stacks.return_value = [stack]
    monkeypatch.setattr('boto.cloudformation.connect_to_region', lambda x: cf)
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

    runner = CliRunner()

    data = {'SenzaInfo': {'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)
        result = runner.invoke(cli, ['delete', 'myapp.yaml', '--region=myregion', '1'],
                               catch_exceptions=False)
        assert 'OK' in result.output

        cf.list_stacks.return_value = [stack, stack]
        result = runner.invoke(cli, ['delete', 'myapp.yaml', '--region=myregion'],
                               catch_exceptions=False)
        assert 'Please use the "--force" flag if you really want to delete multiple stacks' in result.output

        result = runner.invoke(cli, ['delete', 'myapp.yaml', '--region=myregion', '--force'],
                               catch_exceptions=False)
        assert 'OK' in result.output


def test_create(monkeypatch):
    cf = MagicMock()
    sns = MagicMock()
    topic = MagicMock()
    sns.get_all_topics.return_value = {'ListTopicsResponse': {'ListTopicsResult': {'Topics': [topic]}}}
    monkeypatch.setattr('boto.cloudformation.connect_to_region', MagicMock(return_value=cf))
    monkeypatch.setattr('boto.sns.connect_to_region', MagicMock(return_value=sns))
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

    runner = CliRunner()
    data = {'SenzaComponents': [{'Config': {'Type': 'Senza::Configuration'}}],
            'SenzaInfo': {'OperatorTopicId': 'my-topic',
                          'Parameters': [{'MyParam': {'Type': 'String'}}, {'ExtraParam': {'Type': 'String'}}, {'DefParam': {'Type': 'String', 'DefaultValue': 'DefValue'}}],
                          'StackName': 'test'}}

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '1', 'my-param-value', 'extra-param-value'],
                               catch_exceptions=False)
        assert 'DRY-RUN' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--region=myregion', '1', 'my-param-value', 'extra-param-value'],
                               catch_exceptions=False)
        assert 'OK' in result.output

        cf.create_stack.side_effect = boto.exception.BotoServerError('sdf', 'already exists',
                                                                     {'Error': {'Code': 'AlreadyExistsException'}})
        result = runner.invoke(cli, ['create', 'myapp.yaml', '--region=myregion', '1', 'my-param-value', 'extra-param-value'],
                               catch_exceptions=True)
        assert 'Stack test-1 already exists' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--region=myregion', 'abcde'*25, 'my-param-value', 'extra-param-value'],
                               catch_exceptions=True)
        assert 'cannot exceed 128 characters.  Please choose another name/version.' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2'],
                               catch_exceptions=True)
        assert 'Missing parameter' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2', 'p1', 'p2', 'p3', 'p4'],
                               catch_exceptions=True)
        assert 'Too many parameters given' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2', 'my-param-value', 'ExtraParam=extra-param-value'],
                               catch_exceptions=True)
        assert 'OK' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2', 'my-param-value', 'ExtraParam=extra=param=value'],  # checks that equal signs are OK in the keyword param value
                               catch_exceptions=True)
        assert 'OK' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2', 'UnknownParam=value'],
                               catch_exceptions=True)
        assert 'Unrecognized keyword parameter' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2', 'my-param-value', 'MyParam=param-value-again'],
                               catch_exceptions=True)
        assert 'Parameter specified multiple times' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2', 'MyParam=my-param-value', 'MyParam=param-value-again'],
                               catch_exceptions=True)
        assert 'Parameter specified multiple times' in result.output

        result = runner.invoke(cli, ['create', 'myapp.yaml', '--dry-run', '--region=myregion', '2', 'MyParam=my-param-value', 'positional'],
                               catch_exceptions=True)
        assert 'Positional parameters must not follow keywords' in result.output


def test_traffic(monkeypatch):
    r53conn = Mock(name='r53conn')

    monkeypatch.setattr('boto.ec2.connect_to_region', MagicMock())
    monkeypatch.setattr('boto.ec2.elb.connect_to_region', MagicMock())
    monkeypatch.setattr('boto.cloudformation.connect_to_region', MagicMock())
    monkeypatch.setattr('boto.route53.connect_to_region', r53conn)
    stacks = [
        StackVersion('myapp', 'v1', 'myapp.example.org', 'some-lb'),
        StackVersion('myapp', 'v2', 'myapp.example.org', 'another-elb'),
        StackVersion('myapp', 'v3', 'myapp.example.org', 'elb-3'),
        StackVersion('myapp', 'v4', 'myapp.example.org', 'elb-4'),
    ]
    monkeypatch.setattr('senza.traffic.get_stack_versions', MagicMock(return_value=stacks))
    monkeypatch.setattr('boto.iam.connect_to_region', lambda x: MagicMock())

    # start creating mocking of the route53 record sets and Application Versions
    # this is a lot of dirty and nasty code. Please, somebody help this code.

    def record(dns_identifier, weight):
        rec = MagicMock(name=dns_identifier + '-record',
                        weight=weight,
                        identifier=dns_identifier,
                        type='CNAME')
        rec.name = 'myapp.example.org.'
        return rec

    rr = MagicMock()
    records = collections.OrderedDict()

    for ver, percentage in [('v1', 60),
                            ('v2', 30),
                            ('v3', 10),
                            ('v4', 0)]:
        dns_identifier = 'myapp-{}'.format(ver)
        records[dns_identifier] = record(dns_identifier, percentage * PERCENT_RESOLUTION)

    rr.__iter__ = lambda x: iter(records.values())

    def add_change(op, dns_name, rtype, ttl, identifier, weight):
        if op == 'CREATE':
            x = MagicMock(weight=weight, identifier=identifier)
            x.name = "myapp.example.org."
            x.type = "CNAME"
            records[identifier] = x
        return MagicMock(name='change')

    def add_change_record(op, record):
        if op == 'DELETE':
            records[record.identifier].weight = 0
        elif op == 'UPSERT':
            records[record.identifier].weight = record.weight

    rr.add_change = add_change
    rr.add_change_record = add_change_record

    r53conn().get_zone().get_records.return_value = rr

    runner = CliRunner()

    common_opts = ['traffic', '--region=my-region', 'myapp']

    def run(opts):
        result = runner.invoke(cli, common_opts + opts, catch_exceptions=False)
        return result

    def weights():
        return [r.weight for r in records.values()]

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
