'''
HA Postgres app, which needs an S3 bucket to store WAL files
'''

import random
import string

import click
import requests
from clickclick import choice, warning
from senza.aws import (encrypt, get_security_group, get_vpc_attribute,
                       list_kms_keys)
from senza.utils import pystache_render

from ..manaus.boto_proxy import BotoClientProxy
from ._helper import check_s3_bucket, get_account_alias, prompt

POSTGRES_PORT = 5432
HEALTHCHECK_PORT = 8008

# This template goes through 2 formatting phases. Once during the init phase and once during
# the create phase of senza. Some placeholders should be evaluated during create.
# This creates some ugly placeholder formatting, therefore some placeholders are placeholders for placeholders
# - version
# - ImageVersion
TEMPLATE = '''
# basic information for generating and executing this definition
SenzaInfo:
  StackName: spilo
  {{^docker_image}}
  Parameters:
    - ImageVersion:
        Description: "Docker image version of spilo."
  {{/docker_image}}
  Tags:
    - SpiloCluster: "{{version}}"

# a list of senza components to apply to the definition
SenzaComponents:

  # this basic configuration is required for the other components
  - Configuration:
      Type: Senza::StupsAutoConfiguration # auto-detect network setup

  # will create a launch configuration and auto scaling group with scaling triggers
  - AppServer:
      Type: Senza::TaupageAutoScalingGroup
      AutoScaling:
        Minimum: 3
        Maximum: 3
        MetricType: CPU
      InstanceType: {{instance_type}}
      {{#ebs_optimized}}
      EbsOptimized: True
      {{/ebs_optimized}}
      BlockDeviceMappings:
        - DeviceName: /dev/xvdk
          {{#use_ebs}}
          Ebs:
            VolumeSize: {{volume_size}}
            VolumeType: {{volume_type}}
            {{#snapshot_id}}
            SnapshotId: {{snapshot_id}}
            {{/snapshot_id}}
            {{#volume_iops}}
            Iops: {{volume_iops}}
            {{/volume_iops}}
          {{/use_ebs}}
          {{^use_ebs}}
          VirtualName: ephemeral0
          {{/use_ebs}}
      ElasticLoadBalancer:
        - PostgresLoadBalancer
        {{#add_replica_loadbalancer}}
        - PostgresReplicaLoadBalancer
        {{/add_replica_loadbalancer}}
      HealthCheckType: EC2
      SecurityGroups:
        - Fn::GetAtt:
          - SpiloMemberSG
          - GroupId
      IamRoles:
        - Ref: PostgresAccessRole
      AssociatePublicIpAddress: false # change for standalone deployment in default VPC
      TaupageConfig:
        runtime: Docker
        {{#docker_image}}
        source: {{docker_image}}
        {{/docker_image}}
        {{^docker_image}}
        source: "{{ImageVersion}}"
        {{/docker_image}}
        ports:
          {{postgres_port}}: {{postgres_port}}
          {{healthcheck_port}}: {{healthcheck_port}}
        etcd_discovery_domain: "{{discovery_domain}}"
        environment:
          SCOPE: "{{version}}"
          ETCD_DISCOVERY_DOMAIN: "{{discovery_domain}}"
          WAL_S3_BUCKET: "{{wal_s3_bucket}}"
          PGPASSWORD_SUPERUSER: "{{pgpassword_superuser}}"
          PGPASSWORD_ADMIN: "{{pgpassword_admin}}"
          PGPASSWORD_STANDBY: "{{pgpassword_standby}}"
          BACKUP_SCHEDULE: "00 01 * * *"
          PATRONI_CONFIGURATION: | ## https://github.com/zalando/patroni#yaml-configuration
            bootstrap:
              dcs:
                postgresql:
                  parameters:
                    log_connections: on
              pg_hba:
               - hostnossl all all all reject
        root: True
        sysctl:
          vm.overcommit_memory: 2
          vm.overcommit_ratio: 200
          vm.dirty_ratio: 8
          vm.dirty_background_ratio: 1
          vm.swappiness: 1
        appdynamics_application: "postgresapp-{{version}}"
        mounts:
          /home/postgres/pgdata:
            partition: /dev/xvdk
            filesystem: {{fstype}}
            {{#snapshot_id}}
            erase_on_boot: false
            {{/snapshot_id}}
            {{^snapshot_id}}
            erase_on_boot: true
            {{/snapshot_id}}
            options: {{fsoptions}}
Resources:
  {{#add_replica_loadbalancer}}
  PostgresReplicaRoute53Record:
    Type: AWS::Route53::RecordSet
    Properties:
      Type: CNAME
      TTL: 20
      HostedZoneName: {{hosted_zone}}
      Name: "{{version}}-replica.{{hosted_zone}}"
      ResourceRecords:
        - Fn::GetAtt:
           - PostgresReplicaLoadBalancer
           - DNSName
  PostgresReplicaLoadBalancer:
    Type: AWS::ElasticLoadBalancing::LoadBalancer
    Properties:
      CrossZone: true
      HealthCheck:
        HealthyThreshold: 2
        Interval: 5
        Target: HTTP:{{healthcheck_port}}/replica
        Timeout: 3
        UnhealthyThreshold: 2
      Listeners:
        - InstancePort: {{postgres_port}}
          LoadBalancerPort: {{postgres_port}}
          Protocol: TCP
      LoadBalancerName: "spilo-{{version}}-replica"
      ConnectionSettings:
        IdleTimeout: 3600
      SecurityGroups:
        - Fn::GetAtt:
          - SpiloReplicaSG
          - GroupId
      Scheme: internal
      Subnets:
        Fn::FindInMap:
          - LoadBalancerSubnets
          - Ref: AWS::Region
          - Subnets
  {{/add_replica_loadbalancer}}
  PostgresRoute53Record:
    Type: AWS::Route53::RecordSet
    Properties:
      Type: CNAME
      TTL: 20
      HostedZoneName: {{hosted_zone}}
      Name: "{{version}}.{{hosted_zone}}"
      ResourceRecords:
        - Fn::GetAtt:
           - PostgresLoadBalancer
           - DNSName
  PostgresLoadBalancer:
    Type: AWS::ElasticLoadBalancing::LoadBalancer
    Properties:
      CrossZone: true
      HealthCheck:
        HealthyThreshold: 2
        Interval: 5
        Target: HTTP:{{healthcheck_port}}/master
        Timeout: 3
        UnhealthyThreshold: 2
      Listeners:
        - InstancePort: {{postgres_port}}
          LoadBalancerPort: {{postgres_port}}
          Protocol: TCP
      LoadBalancerName: "spilo-{{version}}"
      ConnectionSettings:
        IdleTimeout: 3600
      SecurityGroups:
        - Fn::GetAtt:
          - SpiloMasterSG
          - GroupId
      Scheme: internal
      Subnets:
        Fn::FindInMap:
          - LoadBalancerSubnets
          - Ref: AWS::Region
          - Subnets
  PostgresAccessRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
        - Effect: Allow
          Principal:
            Service: ec2.amazonaws.com
          Action: sts:AssumeRole
      Path: /
      Policies:
      - PolicyName: SpiloEC2S3KMSAccess
        PolicyDocument:
          Version: "2012-10-17"
          Statement:
          - Effect: Allow
            Action:
              - s3:ListBucket
            Resource:
              - "arn:aws:s3:::{{wal_s3_bucket}}"
              - "arn:aws:s3:::{{wal_s3_bucket}}/*"
          - Effect: Allow
            Action:
              - s3:*
            Resource:
              - "arn:aws:s3:::{{wal_s3_bucket}}/spilo/{{version}}/*"
          - Effect: Allow
            Action: ec2:CreateTags
            Resource: "*"
          - Effect: Allow
            Action: ec2:Describe*
            Resource: "*"
          {{#kms_arn}}
          - Effect: Allow
            Action:
              - "kms:Decrypt"
            Resource:
              - {{kms_arn}}
          {{/kms_arn}}
  SpiloMasterSG:
    Type: "AWS::EC2::SecurityGroup"
    Properties:
      GroupDescription: "Security Group for the master ELB of Spilo: {{version}}"
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: {{postgres_port}}
          ToPort: {{postgres_port}}
          CidrIp: {{elb_access_cidr}}
  {{#add_replica_loadbalancer}}
  SpiloReplicaSG:
    Type: "AWS::EC2::SecurityGroup"
    Properties:
      GroupDescription: "Security Group for the replica ELB of Spilo: {{version}}"
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: {{postgres_port}}
          ToPort: {{postgres_port}}
          CidrIp: {{elb_access_cidr}}
  {{/add_replica_loadbalancer}}
  SpiloMemberSG:
    Type: "AWS::EC2::SecurityGroup"
    Properties:
      GroupDescription: "Security Group for members of Spilo: {{version}}"
      SecurityGroupIngress:
        - IpProtocol: tcp
          FromPort: {{postgres_port}}
          ToPort: {{postgres_port}}
          SourceSecurityGroupId:
            Fn::GetAtt:
              - SpiloMasterSG
              - GroupId
        - IpProtocol: tcp
          FromPort: {{healthcheck_port}}
          ToPort: {{healthcheck_port}}
          SourceSecurityGroupId:
            Fn::GetAtt:
              - SpiloMasterSG
              - GroupId

        {{#add_replica_loadbalancer}}
        - IpProtocol: tcp
          FromPort: {{postgres_port}}
          ToPort: {{postgres_port}}
          SourceSecurityGroupId:
            Fn::GetAtt:
              - SpiloReplicaSG
              - GroupId
        - IpProtocol: tcp
          FromPort: {{healthcheck_port}}
          ToPort: {{healthcheck_port}}
          SourceSecurityGroupId:
            Fn::GetAtt:
              - SpiloReplicaSG
              - GroupId
        {{/add_replica_loadbalancer}}
        {{#zmon_sg_id}}
        - IpProtocol: tcp
          FromPort: {{promotheus_port}}
          ToPort: {{promotheus_port}}
          SourceSecurityGroupId: "{{zmon_sg_id}}"
        - IpProtocol: tcp
          FromPort: {{postgres_port}}
          ToPort: {{postgres_port}}
          SourceSecurityGroupId: "{{zmon_sg_id}}"
        - IpProtocol: tcp
          FromPort: {{healthcheck_port}}
          ToPort: {{healthcheck_port}}
          SourceSecurityGroupId: "{{zmon_sg_id}}"
        {{/zmon_sg_id}}
        {{#odd_sg_id}}
        - IpProtocol: tcp
          FromPort: 0
          ToPort: 65535
          SourceSecurityGroupId: "{{odd_sg_id}}"
        {{/odd_sg_id}}
  SpiloMemberIngressMembers:
    Type: "AWS::EC2::SecurityGroupIngress"
    Properties:
      GroupId:
        Fn::GetAtt:
          - SpiloMemberSG
          - GroupId
      IpProtocol: tcp
      FromPort: 0
      ToPort: 65535
      SourceSecurityGroupId:
        Fn::GetAtt:
          - SpiloMemberSG
          - GroupId
'''


def ebs_optimized_supported(instance_type):
    """
    Per http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EBSOptimized.html
    """
    # TODO move to manaus
    return instance_type in ('c1.large', 'c3.xlarge', 'c3.2xlarge', 'c3.4xlarge',
                             'c4.large', 'c4.xlarge', 'c4.2xlarge', 'c4.4xlarge', 'c4.8xlarge',
                             'd2.xlarge', 'd2.2xlarge', 'd2.4xlarge', 'd2.8xlarge',
                             'g2.2xlarge', 'i2.xlarge', 'i2.2xlarge', 'i2.4xlarge',
                             'm1.large', 'm1.xlarge', 'm2.2xlarge', 'm2.4xlarge',
                             'm3.xlarge', 'm3.2xlarge', 'r3.xlarge', 'r3.2xlarge',
                             'r3.4xlarge')


def set_default_variables(variables):
    variables.setdefault('version', '{{Arguments.version}}')
    variables.setdefault('ImageVersion', '{{Arguments.ImageVersion}}')
    variables.setdefault('discovery_domain', 'postgres.example.com')
    variables.setdefault('docker_image', None)
    variables.setdefault('ebs_optimized', None)
    variables.setdefault('elb_access_cidr', '0.0.0.0/0')
    variables.setdefault('fsoptions', 'noatime,nodiratime,nobarrier')
    variables.setdefault('fstype', 'ext4')
    variables.setdefault('healthcheck_port', HEALTHCHECK_PORT)
    variables.setdefault('hosted_zone', 'example.com')
    variables.setdefault('add_replica_loadbalancer', False)
    variables.setdefault('instance_type', 't2.medium')
    variables.setdefault('kms_arn', None)
    variables.setdefault('odd_sg_id', None)
    variables.setdefault('pgpassword_admin', 'admin')
    variables.setdefault('pgpassword_standby', 'standby')
    variables.setdefault('pgpassword_superuser', 'zalando')
    variables.setdefault('postgres_port', POSTGRES_PORT)
    variables.setdefault('promotheus_port', '9100')
    variables.setdefault('snapshot_id', None)
    variables.setdefault('use_ebs', True)
    variables.setdefault('volume_iops', 300)
    variables.setdefault('volume_size', 10)
    variables.setdefault('volume_type', 'gp2')
    variables.setdefault('wal_s3_bucket', None)
    variables.setdefault('zmon_sg_id', None)

    return variables


def gather_user_variables(variables, region, account_info):
    defaults = set_default_variables(dict())

    if click.confirm('Do you want to set the docker image now? [No]'):
        prompt(variables, "docker_image", "Docker Image Version", default=get_latest_image())

    prompt(variables, 'wal_s3_bucket', 'Postgres WAL S3 bucket to use',
           default='{}-{}-spilo-app'.format(get_account_alias(), region))

    prompt(variables, 'instance_type', 'EC2 instance type', default='t2.medium')

    variables['hosted_zone'] = account_info.Domain or defaults['hosted_zone']
    if (variables['hosted_zone'][-1:] != '.'):
        variables['hosted_zone'] += '.'
    prompt(variables, 'discovery_domain', 'ETCD Discovery Domain',
           default='postgres.' + variables['hosted_zone'][:-1])

    variables['add_replica_loadbalancer'] = click.confirm('Do you want a replica ELB?', default=False)

    prompt(variables, 'elb_access_cidr', 'Which network should be allowed to access the ELB''s? (default=vpc)',
           default=get_vpc_attribute(region=region, vpc_id=account_info.VpcID, attribute='cidr_block'))

    odd_sg_name = 'Odd (SSH Bastion Host)'
    odd_sg = get_security_group(region, odd_sg_name)
    if odd_sg and click.confirm('Do you want to allow access to the Spilo nodes from {}?'.format(odd_sg_name),
                                default=True):
        variables['odd_sg_id'] = odd_sg.group_id

    # Find all Security Groups attached to the zmon worker with 'zmon' in their name
    ec2 = BotoClientProxy('ec2', region)
    filters = [{'Name': 'tag-key', 'Values': ['StackName']}, {'Name': 'tag-value', 'Values': ['zmon-appliance']}]
    zmon_sgs = list()
    for reservation in ec2.describe_instances(Filters=filters).get('Reservations', []):
        for instance in reservation.get('Instances', []):
            zmon_sgs += [sg['GroupId'] for sg in instance.get('SecurityGroups', []) if 'zmon' in sg['GroupName']]

    if len(zmon_sgs) == 0:
        warning('Could not find zmon security group, do you have the zmon-appliance deployed?')
    else:
        click.confirm('Do you want to allow access to the Spilo nodes from zmon?', default=True)
        if len(zmon_sgs) > 1:
            prompt(variables, 'zmon_sg_id', 'Which Security Group should we allow access from? {}'.format(zmon_sgs))
        else:
            variables['zmon_sg_id'] = zmon_sgs[0]

    if variables['instance_type'].lower().split('.')[0] in ('c3', 'g2', 'hi1', 'i2', 'm3', 'r3'):
        variables['use_ebs'] = click.confirm('Do you want database data directory on external (EBS) storage? [Yes]',
                                             default=defaults['use_ebs'])
    else:
        variables['use_ebs'] = True

    if variables['use_ebs']:
        prompt(variables, 'volume_size', 'Database volume size (GB, 10 or more)', default=defaults['volume_size'])
        prompt(variables, 'volume_type', 'Database volume type (gp2, io1 or standard)',
               default=defaults['volume_type'])
        if variables['volume_type'] == 'io1':
            pio_max = variables['volume_size'] * 30
            prompt(variables, "volume_iops", 'Provisioned I/O operations per second (100 - {0})'.
                   format(pio_max), default=str(pio_max))
        prompt(variables, "snapshot_id", "ID of the snapshot to populate EBS volume from", default="")
        if ebs_optimized_supported(variables['instance_type']):
            variables['ebs_optimized'] = True
    prompt(variables, "fstype", "Filesystem for the data partition", default=defaults['fstype'])
    prompt(variables, "fsoptions", "Filesystem mount options (comma-separated)",
           default=defaults['fsoptions'])

    prompt(variables, 'pgpassword_superuser', "Password for PostgreSQL superuser [random]", show_default=False,
           default=generate_random_password, hide_input=True, confirmation_prompt=True)
    prompt(variables, 'pgpassword_standby', "Password for PostgreSQL user standby [random]", show_default=False,
           default=generate_random_password, hide_input=True, confirmation_prompt=True)
    prompt(variables, 'pgpassword_admin', "Password for PostgreSQL user admin", show_default=True,
           default=defaults['pgpassword_admin'], hide_input=True, confirmation_prompt=True)

    if click.confirm('Do you wish to encrypt these passwords using KMS?', default=False):
        kms_keys = [k for k in list_kms_keys(region) if 'alias/aws/ebs' not in k['aliases']]

        if len(kms_keys) == 0:
            raise click.UsageError('No KMS key is available for encrypting and decrypting. '
                                   'Ensure you have at least 1 key available.')

        options = ['{}: {}'.format(k['KeyId'], k['Description']) for k in kms_keys]
        kms_key = choice(prompt='Please select the encryption key', options=options)
        kms_keyid = kms_key.split(':')[0]

        variables['kms_arn'] = [k['Arn'] for k in kms_keys if k['KeyId'] == kms_keyid][0]

        for key in [k for k in variables if k.startswith('pgpassword_')]:
            if variables[key]:
                encrypted = encrypt(region=region, KeyId=kms_keyid, Plaintext=variables[key], b64encode=True)
                variables[key] = 'aws:kms:{}'.format(encrypted)

    set_default_variables(variables)

    check_s3_bucket(variables['wal_s3_bucket'], region)

    return variables


def generate_random_password(length=64):
    """
    Generates a random password containing upper case characters and digits
    """
    char_list = string.ascii_uppercase + string.digits
    return ''.join(random.SystemRandom().choice(char_list)
                   for _ in range(length))


def generate_definition(variables):
    definition_yaml = pystache_render(TEMPLATE, variables)
    return definition_yaml


def get_latest_image(registry_domain='registry.opensource.zalan.do', team='acid', artifact='spilo-9.5'):
    """
    Gets the full name of latest image for an artifact
    """
    try:
        r = requests.get('https://{0}/teams/{1}/artifacts/{2}/tags'.format(registry_domain, team, artifact))
        if r.ok:
            # sort the tags by creation date
            latest = None
            for entry in sorted(r.json(), key=lambda t: t['created'], reverse=True):
                tag = entry['name']
                # try to avoid snapshots if possible
                if 'SNAPSHOT' not in tag:
                    latest = tag
                    break
                latest = latest or tag
            return "{0}/{1}/{2}:{3}".format(registry_domain, team, artifact, latest)
    except:
        pass
    return ""
