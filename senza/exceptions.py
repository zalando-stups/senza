class SenzaException(Exception):
    """
    Base class for Senza execeptions
    """


class InvalidState(SenzaException):
    """
    Exception raised when executing an action would try to change a stack
    to an invalid state
    """


class VPCError(SenzaException, AttributeError):
    """
    Error raised when there are issues with VPCs configuration
    """

    def __init__(self, message):
        super().__init__(message)


class PiuNotFound(SenzaException, FileNotFoundError):
    """
    Error raised when piu executable is not found
    """

    def __init__(self):
        super().__init__('Command not found: piu')
