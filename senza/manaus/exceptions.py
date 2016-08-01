class ManausException(Exception):
    """
    Base class for Manaus execeptions
    """


class InvalidState(ManausException):
    """
    Exception raised when executing an action would try to change a stack
    to an invalid state
    """


class ELBNotFound(ManausException):
    """
    Error raised when piu executable is not found
    """

    def __init__(self, domain_name: str):
        super().__init__('ELB not found: {}'.format(domain_name))
