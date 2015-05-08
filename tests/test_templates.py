import json
from mock import MagicMock
from senza.templates._helper import get_iam_role_policy


def test_template_helper_get_iam_role_policy(monkeypatch):
    iam = MagicMock()
    iam.list_roles.return_value = {'list_roles_response': {'list_roles_result': {'is_truncated': 'false', 'roles': [
        {'arn': 'arn:aws:iam::123:role/app-delivery'}]}}}
    iam.get_account_alias.return_value = {
        'list_account_aliases_response': {'list_account_aliases_result': {'account_aliases': ['myorg-foobar']}}
    }
    monkeypatch.setattr('boto.iam.connect_to_region', MagicMock(return_value=iam))

    expected_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowMintRead",
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject",
                    "s3:ListBucket"
                ],
                "Resource": [
                    "arn:aws:s3:::myorg-stups-mint-123-myregion",
                    "arn:aws:s3:::myorg-stups-mint-123-myregion/myapp/*"
                ]
            },
        ]
    }

    assert expected_policy == get_iam_role_policy('myapp', 'myregion')
