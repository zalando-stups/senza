import boto.ec2
import boto.vpc
import boto.s3
import click
import json
from clickclick import Action
from senza.aws import get_security_group

__author__ = 'hjacobs'


def prompt(variables: dict, var_name, *args, **kwargs):
    if var_name not in variables:
        if callable(kwargs.get('default')):
            # evaluate callable
            kwargs['default'] = kwargs['default']()

        variables[var_name] = click.prompt(*args, **kwargs)


def check_security_group(sg_name, rules, region, allow_from_self=False):
    rules_missing = set()
    for rule in rules:
        rules_missing.add(rule)

    with Action('Checking security group {}..'.format(sg_name)):
        sg = get_security_group(region, sg_name)
        if sg:
            for rule in sg.rules:
                # NOTE: boto object has port as string!
                for proto, port in rules:
                    if rule.ip_protocol == proto and rule.from_port == str(port):
                        rules_missing.remove((proto, port))

    if sg:
        return rules_missing
    else:
        create_sg = click.confirm('Security group {} does not exist. Do you want Senza to create it now?'.format(
            sg_name), default=True)
        if create_sg:
            vpc_conn = boto.vpc.connect_to_region(region)
            vpcs = vpc_conn.get_all_vpcs()
            ec2_conn = boto.ec2.connect_to_region(region)
            sg = ec2_conn.create_security_group(sg_name, 'Application security group', vpc_id=vpcs[0].id)
            sg.add_tags({'Name': sg_name})
            for proto, port in rules:
                sg.authorize(ip_protocol=proto, from_port=port, to_port=port, cidr_ip='0.0.0.0/0')
            if allow_from_self:
                sg.authorize(ip_protocol='tcp', from_port=0, to_port=65535, src_group=sg)
        return set()


def get_account_id(region):
    conn = boto.iam.connect_to_region(region)
    roles = conn.list_roles()['list_roles_response']['list_roles_result']['roles']
    if not roles:
        with Action('Creating temporary IAM role to determine account ID..'):
            temp_role_name = 'temp-senza-account-id'
            res = conn.create_role(temp_role_name)
            arn = res['create_role_response']['create_role_result']['role']['arn']
            conn.delete_role(temp_role_name)
    else:
        arn = [r['arn'] for r in roles][0]
    account_id = arn.split(':')[4]
    return account_id


def get_account_alias(region):
    conn = boto.iam.connect_to_region(region)
    resp = conn.get_account_alias()
    return resp['list_account_aliases_response']['list_account_aliases_result']['account_aliases'][0]


def get_mint_bucket_name(region: str):
    account_id = get_account_id(region)
    account_alias = get_account_alias(region)
    parts = account_alias.split('-')
    prefix = parts[0]
    bucket_name = '{}-stups-mint-{}-{}'.format(prefix, account_id, region)
    return bucket_name


def get_iam_role_policy(application_id: str, bucket_name: str, region: str):
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowMintRead",
                "Effect": "Allow",
                "Action": [
                    "s3:GetObject"
                ],
                "Resource": [
                    "arn:aws:s3:::{}/{}/*".format(bucket_name, application_id)
                ]
            },
        ]
    }


def check_iam_role(application_id: str, bucket_name: str, region: str):
    role_name = 'app-{}'.format(application_id)
    with Action('Checking IAM role {}..'.format(role_name)):
        iam = boto.iam.connect_to_region(region)
        exists = False
        try:
            iam.get_role(role_name)
            exists = True
        except:
            pass

    if not exists:
        with Action('Creating IAM role {}..'.format(role_name)):
            iam.create_role(role_name)

    update_policy = not exists or \
        click.confirm('IAM role {} already exists. Do you want Senza to overwrite the role policy?'.format(role_name))
    if update_policy:
        with Action('Updating IAM role policy of {}..'.format(role_name)):
            policy = get_iam_role_policy(application_id, bucket_name, region)
            iam.put_role_policy(role_name, role_name, json.dumps(policy))


def check_s3_bucket(bucket_name: str, region: str):
    with Action("Checking S3 bucket {}..".format(bucket_name)):
        exists = False
        try:
            s3 = boto.s3.connect_to_region(region)
            exists = s3.lookup(bucket_name, validate=True)
        except:
            pass
    if not exists:
        with Action("Creating S3 bucket {}...".format(bucket_name)):
            s3.create_bucket(bucket_name, location=region)
