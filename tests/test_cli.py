
from click.testing import CliRunner
import yaml
from senza.cli import cli


def test_invalid_definition():
    data = {}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '123'], catch_exceptions=False)

    assert 'Error: Invalid value for "definition"' in result.output

def test_print():

    data = {'SenzaInfo': {}, 'SenzaComponents': []}

    runner = CliRunner()

    with runner.isolated_filesystem():
        with open('myapp.yaml', 'w') as fd:
            yaml.dump(data, fd)

        result = runner.invoke(cli, ['print', 'myapp.yaml', '123', '1.0-SNAPSHOT'], catch_exceptions=False)

    assert 'AWSTemplateFormatVersion' in result.output
