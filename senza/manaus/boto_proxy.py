from time import sleep

import boto3
from botocore.exceptions import ClientError

__all__ = ['BotoClientProxy']


class BotoClientProxy:
    def __init__(self, *args, **kwargs):
        self.__client = boto3.client(*args, **kwargs)

    @staticmethod
    def __decorator(function, *args, **kwargs):
        def wrapper(*args, **kwargs):
            max_tries = 5  # TODO make configurable
            sleep_time = 5  # TODO make configurable
            last_error = None
            for i in range(max_tries):
                try:
                    return function(*args, **kwargs)
                except ClientError as error:
                    last_error = error
                    if error.response['Error']['Code'] == "Throttling":
                        sleep(sleep_time)
                    else:
                        raise
            else:
                if last_error:
                    raise last_error
        return wrapper

    def __getattr__(self, item):
        client_attr = getattr(self.__client, item)
        if callable(client_attr):
            return self.__decorator(client_attr)
        else:
            return client_attr
