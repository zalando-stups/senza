from tempfile import NamedTemporaryFile
from traceback import format_exception


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
