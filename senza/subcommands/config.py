from typing import Optional

from click import argument, command
from click.exceptions import BadArgumentUsage

from ..configuration import configuration
from ..exceptions import InvalidConfigKey


@command('config')
@argument('key')
@argument('value', required=False)
def cmd_config(key: str, value: Optional[str]):
    """
    Get and set senza options.
    """
    if value is None:
        try:
            value = configuration[key]
            print(value)
        except InvalidConfigKey as e:
            raise BadArgumentUsage(e)
        except KeyError:
            exit(1)
    else:
        try:
            configuration[key] = value
        except InvalidConfigKey as e:
            raise BadArgumentUsage(e)
