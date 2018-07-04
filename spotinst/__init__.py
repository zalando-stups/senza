"""
Deploy Spotinst Elastigroups using AWS CloudFormation templates
"""
from senza.exceptions import SenzaException

__version__ = '0.1'


class MissingSpotinstAccount(SenzaException):
    """
    Exception raised when failed to map the target cloud account to a spotinst account
    """

    def __init__(self, cloud_account_id: str):
        self.cloud_account_id = cloud_account_id

    def __str__(self):
        return "{cloud_account_id} cloud account was not found in your Spotinst organization ".format_map(vars(self))
