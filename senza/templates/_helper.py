import boto.ec2
import boto.vpc
import click
from clickclick import Action
from senza.aws import get_security_group

__author__ = 'hjacobs'


def prompt(variables: dict, var_name, *args, **kwargs):
    if var_name not in variables:
        variables[var_name] = click.prompt(*args, **kwargs)


def check_security_group(sg_name, rules, region):
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
        return set()
