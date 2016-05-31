class SenzaException(Exception):
    """
    Base class for Senza execeptions
    """


class VPCError(SenzaException, AttributeError):
    """
    Error raised when there are issues with VPCs configuration
    """

    def __init__(self, message):
        super().__init__(message)
