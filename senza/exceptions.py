class SenzaException(Exception):
    """
    Base class for Senza exceptions
    """


class InvalidState(SenzaException):
    """
    Exception raised when executing an action would try to change a stack
    to an invalid state
    """


class PiuNotFound(SenzaException, FileNotFoundError):
    """
    Error raised when piu executable is not found
    """

    def __init__(self):
        super().__init__('Command not found: piu')


class InvalidConfigKey(SenzaException, ValueError):
    """
    Error raised when trying to use an Invalid Config Key
    """

    def __init__(self, message: str):
        super().__init__(message)


class InvalidDefinition(SenzaException):
    """
    Exception raised when trying to parse and invalid senza definition
    """

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason

    def __str__(self):
        return ("{path} is not a valid senza definition: "
                "{reason}".format_map(vars(self)))
