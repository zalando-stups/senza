class ManausException(Exception):
    """
    Base class for Manaus execeptions
    """


class InvalidState(ManausException):
    """
    Exception raised when executing an action would try to change a stack
    to an invalid state
    """
