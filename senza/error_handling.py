"""
Functions to handle exceptions that bubble to the top, including Sentry
integration
"""

import sys
from tempfile import NamedTemporaryFile
from traceback import format_exception
from typing import Optional  # noqa: F401

import yaml.constructor
from botocore.exceptions import ClientError, NoCredentialsError
from clickclick import fatal_error
from raven import Client

import senza
from .configuration import configuration
from .exceptions import (InvalidDefinition, InvalidUserDataType,
                         PiuNotFound, SecurityGroupNotFound,
                         InvalidParameterFile)
from .manaus.exceptions import (ELBNotFound, HostedZoneNotFound, InvalidState,
                                RecordNotFound)
from .manaus.utils import extract_client_error_code


def store_exception(exception: Exception) -> str:
    """
    Stores the exception in a temporary file and returns its filename
    """

    tracebacks = format_exception(etype=type(exception),
                                  value=exception,
                                  tb=exception.__traceback__)  # type: [str]

    content = ''.join(tracebacks)

    with NamedTemporaryFile(prefix="senza-traceback-",
                            delete=False) as error_file:
        file_name = error_file.name
        error_file.write(content.encode())

    return file_name


def is_credentials_expired_error(client_error: ClientError) -> bool:
    """Return true if the exception's error code is ExpiredToken or RequestExpired"""
    return extract_client_error_code(client_error) in ['ExpiredToken',
                                                       'RequestExpired']


def is_access_denied_error(client_error: ClientError) -> bool:
    """
    Checks the ``ClientError`` details to find out if it is an
    Access Denied Error
    """
    return extract_client_error_code(client_error) in ['AccessDenied']


def is_validation_error(client_error: ClientError) -> bool:
    """
    Checks the ``ClientError`` details to find out if it is an
    Validation Error
    """
    return extract_client_error_code(client_error) == 'ValidationError'


def die_fatal_error(message):
    """Sent error message to stderr, in red, and exit"""
    fatal_error(message, err=True)


class HandleExceptions:
    """Class HandleExceptions will display various error messages
    depending on the type of the exception and show the stacktrace for general exceptions
    depending on the value of stacktrace_visible"""

    stacktrace_visible = False

    def __init__(self, function):
        self.function = function

    def die_unknown_error(self, unknown_exception: Exception):
        """
        Handles unknown exceptions, shipping them to sentry if it's configured.

        If stacktrace_visible the stacktrace will be printed otherwise the
        stacktrace will be stored in a temporary file or sent to sentry.
        """
        if sentry:
            # The exception should always be sent to sentry if sentry is
            # configured
            sentry.captureException()
        if self.stacktrace_visible:
            raise unknown_exception
        elif sentry:
            die_fatal_error("Unknown Error: {e}.\n"
                            "This error will be pushed to sentry ".format(
                                e=unknown_exception))
        elif not sentry:
            file_name = store_exception(unknown_exception)
            die_fatal_error('Unknown Error: {e}.\n'
                            'Please create an issue with the '
                            'content of {fn}'.format(e=unknown_exception,
                                                     fn=file_name))

    def __call__(self, *args, **kwargs):
        try:
            self.function(*args, **kwargs)
        except NoCredentialsError:
            die_fatal_error(
                'No AWS credentials found. Use the "zaws" command-line tool '
                'to get a temporary access key\n'
                'or manually configure either ~/.aws/credentials '
                'or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY.')
        except ClientError as client_error:
            sys.stdout.flush()
            if is_credentials_expired_error(client_error):
                die_fatal_error('AWS credentials have expired.\n'
                                'Use the "zaws" command line tool to get a new '
                                'temporary access key.')
            elif is_access_denied_error(client_error):
                die_fatal_error(
                    "AWS missing access rights.\n{}".format(
                        client_error.response['Error']['Message']))
            elif is_validation_error(client_error):
                die_fatal_error(
                    "Validation Error: {}".format(
                        client_error.response['Error']['Message']))
            else:
                self.die_unknown_error(client_error)
        except yaml.constructor.ConstructorError as yaml_error:
            err_mesg = "Error parsing definition file:\n{}".format(yaml_error)
            if yaml_error.problem == "found unhashable key":
                err_mesg += "Please quote all variable values"
            die_fatal_error(err_mesg)
        except PiuNotFound as error:
            die_fatal_error(
                "{}\nYou can install piu with the following command:"
                "\nsudo pip3 install --upgrade stups-piu".format(error))
        except (ELBNotFound, HostedZoneNotFound, RecordNotFound,
                InvalidDefinition, InvalidState, InvalidUserDataType,
                InvalidParameterFile) as error:
            die_fatal_error(error)
        except SecurityGroupNotFound as error:
            message = ("{}\nRun `senza init` to (re-)create "
                       "the security group.").format(error)
            die_fatal_error(message)
        except Exception as unknown_exception:  # pylint: disable=locally-disabled, broad-except
            # Catch All
            self.die_unknown_error(unknown_exception)


def setup_sentry(sentry_endpoint: Optional[str]):
    """
    This function setups sentry, this exists mostly to make sentry integration
    easier to test
    """
    if sentry_endpoint is not None:
        sentry_client = Client(sentry_endpoint,
                               release=senza.__version__)
    else:
        sentry_client = None

    return sentry_client


sentry = setup_sentry(configuration.get(
    'sentry.endpoint'))  # pylint: disable=locally-disabled, invalid-name
