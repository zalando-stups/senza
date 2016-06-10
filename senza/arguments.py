import os
from urllib.error import URLError
from urllib.parse import quote
from urllib.request import urlopen

import yaml
from click import Choice, IntRange, ParamType, option


class DefinitionParamType(ParamType):
    name = 'definition'

    def convert(self, value, param, ctx):
        if isinstance(value, str):
            try:
                url = (value if '://' in value
                       else 'file://{}'.format(quote(os.path.abspath(value))))
                response = urlopen(url)
                data = yaml.safe_load(response.read())
            except URLError:
                self.fail('"{}" not found'.format(value), param, ctx)
        else:
            data = value
        for key in ['SenzaInfo']:
            if 'SenzaInfo' not in data:
                self.fail('"{}" entry is missing in YAML file "{}"'.format(key, value),
                          param, ctx)
        return data


class KeyValParamType(ParamType):
    """
    >>> KeyValParamType().convert(('a', 'b'), None, None)
    ('a', 'b')
    """
    name = 'key_val'

    def convert(self, value, param, ctx):
        if isinstance(value, str):
            try:
                key, val = value.split('=', 1)
            except ValueError:
                self.fail('invalid key value parameter "{}" (must be KEY=VAL)'.format(value))
            key_val = (key, val)
        else:
            key_val = value
        return key_val


definition_files_option = option('-d', '--definition',
                                 help='Senza definition files to extract references from.',
                                 nargs=2,
                                 multiple=True)

json_output_option = option('-o', '--output', type=Choice(['json', 'yaml']),
                            default='json',
                            help='Use alternative output format')

parameter_file_option = option('--parameter-file',
                               help='Config file for params',
                               metavar='PATH')

output_option = option('-o', '--output', type=Choice(['text', 'json', 'tsv']),
                       default='text',
                       help='Use alternative output format')

region_option = option('--region', envvar='AWS_DEFAULT_REGION',
                       metavar='AWS_REGION_ID',
                       help='AWS region ID (e.g. eu-west-1)')

watch_option = option('-W', is_flag=True,
                      help='Auto update the screen every 2 seconds')

watchrefresh_option = option('-w', '--watch', type=IntRange(1, 300),
                             metavar='SECS',
                             help='Auto update the screen every X seconds')
