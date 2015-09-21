
import boto3
from senza.utils import ensure_keys


def get_merged_policies(roles: list):
    iam = boto3.resource('iam')
    policies = []
    for rolename in roles:
        role = iam.Role(rolename)
        for policy in role.policies.all():
            policies.append({'PolicyName': policy.policy_name,
                             'PolicyDocument': policy.policy_document})
    return policies


def component_iam_role(definition, configuration, args, info, force, account_info):
    definition = ensure_keys(definition, "Resources")
    role_name = configuration['Name']
    definition['Resources'][role_name] = {
        'Type': 'AWS::IAM::Role',
        'Properties': {
            "AssumeRolePolicyDocument": configuration.get('AssumeRolePolicyDocument', {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {
                            "Service": ["ec2.amazonaws.com"]
                        },
                        "Action": ["sts:AssumeRole"]
                    }
                ]
            }),
            'Path': configuration.get('Path', '/'),
            'Policies': configuration.get('Policies', []) + get_merged_policies(
                configuration.get('MergePoliciesFromIamRoles', []))
        }
    }
    return definition
