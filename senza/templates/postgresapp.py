'''
HA Postgres app, which needs an S3 bucket to store WAL files
'''

from clickclick import warning, error
from senza.aws import get_security_group
from senza.components import get_default_zone
import pystache

from ._helper import prompt, check_security_group, check_s3_bucket, get_mint_bucket_name

POSTGRES_PORT = 5432
HEALTHCHECK_PORT = 8008

TEMPLATE = '''
# basic information for generating and executing this definition
SenzaInfo:
  StackName: spilo
  Parameters:
    - ImageVersion:
        Description: "Docker image version of spilo."

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
          Ebs:
            VolumeSize: {{volume_size}}
            VolumeType: {{volume_type}}
            {{#snapshot_id}}
            SnapshotId: {{snapshot_id}}
            {{/snapshot_id}}
            {{#volume_iops}}
            Iops: {{volume_iops}}
            {{/volume_iops}}
      ElasticLoadBalancer: PostgresLoadBalancer
      HealthCheckType: EC2
      LoadBalancerNames:
        - Ref: PostgresLoadBalancer
      SecurityGroups:
        - app-spilo
      IamRoles:
        - Ref: PostgresAccessRole
      AssociatePublicIpAddress: false # change for standalone deployment in default VPC
      TaupageConfig:
        runtime: Docker
        source: "{{=<% %>=}}{{Arguments.ImageVersion}}<%={{ }}=%>"
        ports:
          {{postgres_port}}: {{postgres_port}}
          {{healthcheck_port}}: {{healthcheck_port}}
        etcd_discovery_domain: "{{discovery_domain}}"
        environment:
          SCOPE: "{{=<% %>=}}{{Arguments.version}}<%={{ }}=%>"
          ETCD_DISCOVERY_DOMAIN: "{{discovery_domain}}"
          WAL_S3_BUCKET: "{{wal_s3_bucket}}"
        root: True
        mounts:
          /home/postgres/pgdata:
            partition: /dev/xvdk
            filesystem: {{fstype}}
            erase_on_boot: true
            options: {{fsoptions}}
        mint_bucket: {{mint_bucket}}
        {{#scalyr_account_key}}
        scalyr_account_key: {{scalyr_account_key}}
        {{/scalyr_account_key}}
Resources:
  PostgresRoute53Record:
    Type: AWS::Route53::RecordSet
    Properties:
      Type: CNAME
      TTL: 20
      HostedZoneName: {{hosted_zone}}
      Name: "{{=<% %>=}}{{Arguments.version}}<%={{ }}=%>.{{hosted_zone}}"
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
        - InstancePort: 5432
          LoadBalancerPort: 5432
          Protocol: TCP
      LoadBalancerName: "spilo-{{=<% %>=}}{{Arguments.version}}<%={{ }}=%>"
      SecurityGroups:
        - {{spilo_sg_id}}
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
      - PolicyName: SpiloEC2S3Access
        PolicyDocument:
          Version: "2012-10-17"
          Statement:
          - Effect: Allow
            Action: s3:*
            Resource:
              - arn:aws:s3:::{{wal_s3_bucket}}/spilo/*
              - arn:aws:s3:::{{wal_s3_bucket}}
          - Effect: Allow
            Action: s3:GetObject
            Resource:
              - arn:aws:s3:::{{mint_bucket}}/spilo/*
              - arn:aws:s3:::{{mint_bucket}}
          - Effect: Allow
            Action: ec2:CreateTags
            Resource: "*"
          - Effect: Allow
            Action: ec2:Describe*
            Resource: "*"
'''


def ebs_optimized_supported(instance_type):
    # per http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EBSOptimized.html
    return instance_type in ('c1.large', 'c3.xlarge', 'c3.2xlarge', 'c3.4xlarge',
                             'c4.large', 'c4.xlarge', 'c4.2xlarge', 'c4.4xlarge', 'c4.8xlarge',
                             'd2.xlarge', 'd2.2xlarge', 'd2.4xlarge', 'd2.8xlarge',
                             'g2.2xlarge', 'i2.xlarge', 'i2.2xlarge', 'i2.4xlarge',
                             'm1.large', 'm1.xlarge', 'm2.2xlarge', 'm2.4xlarge',
                             'm3.xlarge', 'm3.2xlarge', 'r3.xlarge', 'r3.2xlarge',
                             'r3.4xlarge')


def gather_user_variables(variables, region):
    prompt(variables, 'wal_s3_bucket', 'Postgres WAL S3 bucket to use', default='zalando-spilo-app')
    prompt(variables, 'instance_type', 'EC2 instance type', default='t2.micro')
    if ebs_optimized_supported(variables['instance_type']):
        variables['ebs_optimized'] = True
    prompt(variables, 'hosted_zone', 'Hosted Zone', default=get_default_zone(region) or 'example.com')
    if (variables['hosted_zone'][-1:] != '.'):
        variables['hosted_zone'] += '.'
    prompt(variables, 'discovery_domain', 'ETCD Discovery Domain',
           default='postgres.'+variables['hosted_zone'][:-1])
    prompt(variables, 'volume_size', 'Database volume size (GB, 10 or more)', default=10)
    prompt(variables, 'volume_type', 'Database volume type (gp2, io1 or standard)', default='gp2')
    if variables['volume_type'] == 'io1':
        pio_max = variables['volume_size'] * 30
        prompt(variables, "volume_iops", 'Provisioned I/O operations per second (100 - {0})'.format(pio_max),
               default=str(int(pio_max/2)))
    prompt(variables, "snapshot_id", "ID of the snapshot to populate EBS volume from", default="")
    prompt(variables, "fstype", "Filesystem for the data partition", default="ext4")
    prompt(variables, "fsoptions", "Filesystem mount options (comma-separated)",
           default="noatime,nodiratime,nobarrier")
    prompt(variables, 'mint_bucket', 'Mint S3 bucket name', default=lambda: get_mint_bucket_name(region))
    prompt(variables, "scalyr_account_key", "Account key for your scalyr account", "")

    variables['postgres_port'] = POSTGRES_PORT
    variables['healthcheck_port'] = HEALTHCHECK_PORT

    sg_name = 'app-spilo'
    variables['spilo_sg_id'] = get_security_group(region, sg_name).id
    rules_missing = check_security_group(sg_name,
                                         [('tcp', 22), ('tcp', POSTGRES_PORT), ('tcp', HEALTHCHECK_PORT)],
                                         region, allow_from_self=True)

    if ('tcp', 22) in rules_missing:
        warning('Security group {} does not allow SSH access, you will not be able to ssh into your servers'.format(
            sg_name))

    if ('tcp', POSTGRES_PORT) in rules_missing:
        error('Security group {} does not allow inbound TCP traffic on the default postgres port ({})'.format(
            sg_name, POSTGRES_PORT
        ))

    if ('tcp', HEALTHCHECK_PORT) in rules_missing:
        error('Security group {} does not allow inbound TCP traffic on the default health check port ({})'.format(
            sg_name, HEALTHCHECK_PORT
        ))

    check_s3_bucket(variables['wal_s3_bucket'], region)

    return variables


def generate_definition(variables):
    definition_yaml = pystache.render(TEMPLATE, variables)
    return definition_yaml
