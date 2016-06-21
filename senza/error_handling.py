import sys
from tempfile import NamedTemporaryFile
from traceback import format_exception

from botocore.exceptions import ClientError, NoCredentialsError


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


def is_credentials_expired_error(e: ClientError) -> bool:
    return e.response['Error']['Code'] in ['ExpiredToken', 'RequestExpired']


class HandleExceptions:

    stacktrace_visible = False

    def __init__(self, function):
        self.function = function

    def __call__(self, *args, **kwargs):
        try:
            self.function(*args, **kwargs)
        except NoCredentialsError as e:
            print('No AWS credentials found. Use the "mai" command-line tool '
                  'to get a temporary access key\n'
                  'or manually configure either ~/.aws/credentials '
                  'or AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY.',
                  file=sys.stderr)
            sys.exit(1)
        except ClientError as e:
            sys.stdout.flush()
            if is_credentials_expired_error(e):
                print('AWS credentials have expired.\n'
                      'Use the "mai" command line tool to get a new'
                      ' temporary access key.',
                      file=sys.stderr)
                sys.exit(1)
            else:
                if not self.stacktrace_visible:
                    file_name = store_exception(e)
                    print('Unknown Error: {e}.\n'
                          'Please create an issue '
                          'with the content of {fn}'.format(e=e,
                                                            fn=file_name))
                    sys.exit(1)
                else:
                    raise
        except Exception as e:
            # Catch All
            if not self.stacktrace_visible:
                file_name = store_exception(e)
                print('Unknown Error: {e}.\n'
                      'Please create an issue '
                      'with the content of {fn}'.format(e=e, fn=file_name))
                sys.exit(1)
            else:
                raise
