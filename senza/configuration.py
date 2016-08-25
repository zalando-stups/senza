from collections.abc import MutableMapping
from pathlib import Path
from typing import Dict, Tuple

import yaml
from click import get_app_dir


class Configuration(MutableMapping):

    def __init__(self):
        self.config_path = Path(get_app_dir('senza')) / "config.yaml"

    def __iter__(self):
        yield from self.dict

    def __len__(self):
        return len(self.dict)

    def __getitem__(self, key: str) -> str:
        section, sub_key = self.__split_key(key)
        return self.dict[section][sub_key]

    def __setitem__(self, key: str, value):
        section, sub_key = self.__split_key(key)
        configuration = self.dict

        if section not in configuration:
            configuration[section] = {}
        configuration[section][sub_key] = str(value)
        self.__save(configuration)

    def __delitem__(self, key):
        section, sub_key = self.__split_key(key)
        cfg = self.dict
        del cfg[section][sub_key]
        self.__save(cfg)

    @staticmethod
    def __split_key(key: str) -> Tuple[str, str]:
        # TODO exception
        section, sub_key = key.split('.')
        return section, sub_key

    def __save(self, cfg):
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        with self.config_path.open('w+') as config_file:
            yaml.safe_dump(cfg, config_file,
                           default_flow_style=False)

    @property
    def dict(self) -> Dict[str, Dict[str, str]]:
        try:
            with self.config_path.open() as config_file:
                cfg = yaml.safe_load(config_file)
        except FileNotFoundError:
            cfg = {}
        return cfg

configuration = Configuration()
