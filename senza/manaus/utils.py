"""
Generic functions related to AWS/Boto/Manaus but don't belong to any specific
component
"""

from typing import Dict, Optional  # noqa: F401

from botocore.exceptions import ClientError

__all__ = ["extract_client_error_code"]


def extract_client_error_code(exception: ClientError) -> Optional[str]:
    """
    Extracts the client error code from a boto ClientError exception. Returns
    None if it fails.
    """
    error = exception.response.get('Error', {})  # type: Dict[str, Optional[str]]
    error_code = error.get('Code')
    return error_code
