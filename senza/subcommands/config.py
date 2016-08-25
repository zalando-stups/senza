from typing import Optional

from click import argument, command
from click.exceptions import BadArgumentUsage

from ..configuration import configuration


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
        except KeyError:
            raise BadArgumentUsage("Error: key doesn't "
                                   "contain a section: {}".format(key))
    else:
        try:
            configuration[key] = value
        except KeyError:
            raise BadArgumentUsage("Error: key doesn't "
                                   "contain a section: {}".format(key))
