from pathlib import Path
from typing import Dict, Optional

import yaml
from click import argument, command, get_app_dir
from click.exceptions import BadArgumentUsage


def load_config() -> Dict[str, Dict[str, str]]:
    config_path = Path(get_app_dir('senza')) / "config.yaml"
    try:
        with config_path.open() as config_file:
            configuration = yaml.safe_load(config_file)  # type: Dict
    except FileNotFoundError:
        configuration = {}
    return configuration


def save_config(configuration: Dict):
    config_path = Path(get_app_dir('senza')) / "config.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open('w+') as config_file:
        yaml.safe_dump(configuration, config_file,
                       default_flow_style=False)


@command('config')
@argument('key')
@argument('value', required=False)
def cmd_config(key: str, value: Optional[str]):
    """
    Get and set senza options.
    """
    try:
        section, sub_key = key.split('.')
    except ValueError:
        raise BadArgumentUsage("Error: key doesn't "
                               "contain a section: {}".format(key))
    print(section, sub_key, value)

    configuration = load_config()

    if value is None:
        try:
            value = configuration[section][sub_key]
            print(value)
        except KeyError:
            exit(1)
    else:
        if section not in configuration:
            configuration[section] = {}
        configuration[section][sub_key] = value
        save_config(configuration)
