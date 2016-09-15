import sys
from tempfile import NamedTemporaryFile
from traceback import format_exception
from typing import Any, Dict, Optional  # noqa: F401

import senza
import yaml.constructor
from botocore.exceptions import ClientError, NoCredentialsError
from clickclick import fatal_error
from raven import Client

from .configuration import configuration
from .exceptions import InvalidDefinition, PiuNotFound
from .manaus.exceptions import (ELBNotFound, HostedZoneNotFound, InvalidState,
                                RecordNotFound)


def store_exception(exception: Exception) -> str:
    """
    Stores the exception in a temporary file and returns its filename
    """

    tracebacks = format_exception(etype=type(exception),
                                  value=exception,
                                  tb=exception.__traceback__)  # type: [str]

    content = ''.join(tracebacks)

    with NamedTemporaryFile(prefix="senza-traceback-", delete=False) as error_file:
        file_name = error_file.name
        error_file.write(content.encode())

    return file_name


def is_credentials_expired_error(client_error: ClientError) -> bool:
    """Return true if the exception's error code is ExpiredToken or RequestExpired"""
    return client_error.response['Error']['Code'] in ['ExpiredToken', 'RequestExpired']


def is_access_denied_error(e: ClientError) -> bool:
    return e.response['Error']['Code'] in ['AccessDenied']


def is_validation_error(e: ClientError) -> bool:
    return e.response['Error']['Code'] == 'ValidationError'


def die_fatal_error(mesg):
    """Sent error message to stderr, in red, and exit"""
    fatal_error(mesg, err=True)


class HandleExceptions:
    """Class HandleExceptions will display various error messages
    depending on the type of the exception and show the stacktrack for general exceptions
    depending on the value of stacktrace_visible"""

    stacktrace_visible = False

    def __init__(self, function):
        self.function = function

    def die_unknown_error(self, e: Exception):
        if sentry:
            # The exception should always be sent to sentry if sentry is
            # configured
            sentry.captureException()
        if self.stacktrace_visible:
            raise e
        elif sentry:
            die_fatal_error("Unknown Error: {e}.\n"
                            "This error will be pushed to sentry ".format(e=e))
        elif not sentry:
            file_name = store_exception(e)
            die_fatal_error('Unknown Error: {e}.\n'
                            'Please create an issue with the '
                            'content of {fn}'.format(e=e, fn=file_name))

    def __call__(self, *args, **kwargs):
        try:
            self.function(*args, **kwargs)
        except NoCredentialsError:
            die_fatal_error(
                'No AWS credentials found. Use the "mai" command-line tool '
                'to get a temporary access key\n'
                'or manually configure either ~/.aws/credentials '
                'or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY.')
        except ClientError as e:
            sys.stdout.flush()
            if is_credentials_expired_error(e):
                die_fatal_error('AWS credentials have expired.\n'
                                'Use the "mai" command line tool to get a new '
                                'temporary access key.')
            elif is_access_denied_error(e):
                die_fatal_error(
                    "AWS missing access rights.\n{}".format(
                        e.response['Error']['Message']))
            elif is_validation_error(e):
                die_fatal_error(
                    "Validation Error: {}".format(
                        e.response['Error']['Message']))
            else:
                self.die_unknown_error(e)
        except yaml.constructor.ConstructorError as e:
            err_mesg = "Error parsing definition file:\n{}".format(e)
            if e.problem == "found unhashable key":
                err_mesg += "Please quote all variable values"
            die_fatal_error(err_mesg)
        except PiuNotFound as e:
            die_fatal_error(
                "{}\nYou can install piu with the following command:"
                "\nsudo pip3 install --upgrade stups-piu".format(e))
        except InvalidState as e:
            die_fatal_error('Invalid State: {}'.format(e))
        except (ELBNotFound, HostedZoneNotFound, RecordNotFound,
                InvalidDefinition) as e:
            die_fatal_error(e)
        except Exception as e:
            # Catch All
            self.die_unknown_error(e)


def setup_sentry(sentry_endpoint: Optional[str]):
    """
    This function setups sentry, this exists mostly to make sentry integration
    easier to test
    """
    if sentry_endpoint is not None:
        sentry = Client(sentry_endpoint,
                        release=senza.__version__)
    else:
        sentry = None

    return sentry

sentry = setup_sentry(configuration.get('sentry.endpoint'))
