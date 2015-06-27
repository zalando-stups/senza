
import boto.iam
import json
import urllib

from senza.utils import ensure_keys


def get_merged_policies(roles: list, region: str):
    iam = boto.iam.connect_to_region(region)
    policies = []
    for role in roles:
        policy_names = iam.list_role_policies(role)
        for policy_name in policy_names['list_role_policies_response']['list_role_policies_result']['policy_names']:
            policy = iam.get_role_policy(role, policy_name)['get_role_policy_response']['get_role_policy_result']
            document = urllib.parse.unquote(policy['policy_document'])
            policies.append({'PolicyName': policy_name,
                             'PolicyDocument': json.loads(document)})
    return policies


def component_iam_role(definition, configuration, args, info, force):
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
                configuration.get('MergePoliciesFromIamRoles', []), args.region)
        }
    }
    return definition
