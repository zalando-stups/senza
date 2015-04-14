import datetime
import boto.ec2
import boto.iam
import time


def get_security_group(region: str, sg_name: str):
    conn = boto.ec2.connect_to_region(region)
    all_security_groups = conn.get_all_security_groups()
    for _sg in all_security_groups:
        if _sg.name == sg_name:
            return _sg


def find_ssl_certificate_arn(region, pattern):
    '''Find the a matching SSL cert and return its ARN'''
    iam_conn = boto.iam.connect_to_region(region)
    response = iam_conn.list_server_certs()
    response = response['list_server_certificates_response']
    certs = response['list_server_certificates_result']['server_certificate_metadata_list']
    candidates = set()
    for cert in certs:
        if pattern in cert['server_certificate_name']:
            candidates.add(cert['arn'])
    if candidates:
        # return first match (alphabetically sorted
        return sorted(candidates)[0]
    else:
        return None


def parse_time(s: str) -> float:
    try:
        utc = datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%S.%fZ').timestamp()
        return utc - time.timezone
    except:
        return None
