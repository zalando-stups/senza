import os

import click

import yaml


def get_path(section):
    # "old" style config files (one file per app)
    directory = click.get_app_dir(section)
    path = os.path.join(directory, '{}.yaml'.format(section))
    return path


def load_config(section):
    '''Get configuration for given section/project
    Tries to load YAML configuration file and also considers environment variables'''
    path = get_path(section)
    try:
        with open(path, 'rb') as fd:
            config = yaml.safe_load(fd)
    except:
        config = None
    config = config or {}
    return config


def load_output_format(cmd):
    existing_config = load_config('senza')
    return existing_config['outputFormats'][cmd]


def row_data(stack, output_format):
    row_dict = {}
    for column in output_format:
        if 'col' in column:
            if 'alias' in column:
                row_col = column['alias']
            else:
                row_col = column['col']
            row_dict[row_col] = getattr(stack, column['col'])
            # if 'max-length' in column:
            #     value_length = len(row_dict[row_col])
            #     row_dict[row_col] = row_dict[row_col][0:column['max-length']]
            #     if value_length > column['max-length']:
            #         row_dict[row_col] = row_dict[row_col] + '...'
    return row_dict


# rows.append({'stack_name': stack.name,
#                          'stack_name': stack.name,
#                          'version': stack.version,
#                          'status': stack.StackStatus,
#                          'creation_time': calendar.timegm(stack.CreationTime.timetuple()),
#                          'description': stack.TemplateDescription})
