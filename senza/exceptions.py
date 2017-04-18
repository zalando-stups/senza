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
    Exception raised when trying to parse an invalid senza definition
    """

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason

    def __str__(self):
        return ("{path} is not a valid senza definition: "
                "{reason}".format_map(vars(self)))


class InvalidParameterFile(SenzaException):
    """
    Exception raised when trying to parse an invalid parameter
    """

    def __init__(self, path: str, reason: str):
        self.path = path
        self.reason = reason

    def __str__(self):
        return ("{path} is not a valid parameter: "
                "{reason}".format_map(vars(self)))


class SecurityGroupNotFound(SenzaException):
    """
    Exception raised when a Security Group is not found
    """

    def __init__(self, security_group: str):
        self.security_group = security_group

    def __str__(self):
        return 'Security Group "{}" does not exist.'.format(self.security_group)


class InvalidUserDataType(SenzaException):
    """
    Exception raised when the type of the new user data is different from the
    old user data
    """

    def __init__(self, old_type: type, new_type: type):
        self.old_type = old_type
        self.new_type = new_type

    def __str__(self):
        return ('Current user data is a {} but provided user data '
                'is a {}.').format(self.__human_readable_type(self.old_type),
                                   self.__human_readable_type(self.new_type))

    def __human_readable_type(self, t) -> str:
        if t is str:
            return "string"
        elif t is dict:
            return "map"
        elif t is int:
            return 'integer'
        else:
            return str(t)
