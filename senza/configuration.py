"""
Class and instance to read and write senza configuration.

Senza configuration consists of an hierarchical yaml file with
sections > keys > values, which are represented in the form SECTION.KEY
"""

from collections.abc import MutableMapping
from pathlib import Path
from typing import Dict, Tuple

import yaml
from click import get_app_dir

from .exceptions import InvalidConfigKey

CONFIGURATION_PATH = Path(get_app_dir('senza')) / "config.yaml"


class Configuration(MutableMapping):

    """
    Class to read and write senza configuration as map. Keys take the form of
    SECTION.KEY
    """

    def __init__(self, path: Path):
        self.config_path = path

    def __iter__(self):
        yield from self.raw_dict

    def __len__(self):
        return len(self.raw_dict)

    def __getitem__(self, key: str) -> str:
        section, sub_key = self.__split_key(key)
        return self.raw_dict[section][sub_key]

    def __setitem__(self, key: str, value):
        section, sub_key = self.__split_key(key)
        cfg = self.raw_dict

        if section not in self.raw_dict:
            cfg[section] = {}
        cfg[section][sub_key] = str(value)
        self.__save(cfg)

    def __delitem__(self, key):
        section, sub_key = self.__split_key(key)
        cfg = self.raw_dict
        del cfg[section][sub_key]
        self.__save(cfg)

    @staticmethod
    def __split_key(key: str) -> Tuple[str, str]:
        """
        Splits the full key in section and subkey
        """
        try:
            section, sub_key = key.split('.', 1)
        except ValueError:
            # error message inspired by git config
            raise InvalidConfigKey('key does not contain '
                                   'a section: {}'.format(key))
        return section, sub_key

    def __save(self, cfg):
        """
        Saves the configuration in the configuration path, creating the
        directory if necessary.
        """
        try:
            self.config_path.parent.mkdir(parents=True)
        except FileExistsError:
            # this try...except can be replaced with exist_ok=True when
            # we drop python3.4 support
            pass
        with self.config_path.open('w+') as config_file:
            yaml.safe_dump(cfg, config_file,
                           default_flow_style=False)

    @property
    def raw_dict(self) -> Dict[str, Dict[str, str]]:
        """
        Returns a dict with the configuration data as stored in config.yaml
        """
        try:
            with self.config_path.open() as config_file:
                cfg = yaml.safe_load(config_file)
        except FileNotFoundError:
            cfg = {}
        return cfg


configuration = Configuration(CONFIGURATION_PATH)  # pylint: disable=locally-disabled, invalid-name
