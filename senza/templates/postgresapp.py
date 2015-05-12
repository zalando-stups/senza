'''
HA Postgres app, which needs an S3 bucket to store WAL files
'''

from clickclick import warning, error
import pystache

from ._helper import prompt, check_security_group, check_s3_bucket

POSTGRES_PORT = 5432

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
      SecurityGroups:
        - app-spilo
      IamRoles:
        - Ref: PostgresS3AccessRole
      TaupageConfig:
        runtime: Docker
        source: "{{=<% %>=}}{{Arguments.ImageVersion}}<%={{ }}=%>"
        ports:
          5432: 5432
        environment:
          SCOPE: "{{=<% %>=}}{{Arguments.version}}<%={{ }}=%>"
          ETCD_DISCOVERY_URL: "{{discovery_url}}"
          WAL_S3_BUCKET: "{{wal_s3_bucket}}"
        root: True
Resources:
  PostgresS3AccessRole:
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
      - PolicyName: AmazonEC2ReadOnlyAccess
        PolicyDocument:
          Version: "2012-10-17"
          Statement:
          - Effect: Allow
            Action: "s3:*"
            Resource: "*"
'''


def gather_user_variables(variables, region):
    prompt(variables, 'wal_s3_bucket', 'Postgres WAL S3 bucket to use', default='zalando-spilo-app')
    prompt(variables, 'instance_type', 'EC2 instance type', default='t2.micro')
    prompt(variables, 'discovery_url', 'ETCD Discovery URL', default='postgres.acid.example.com')

    sg_name = 'app-spilo'
    rules_missing = check_security_group(sg_name, [('tcp', 22), ('tcp', POSTGRES_PORT)], region,
                                         allow_from_self=True)

    if ('tcp', 22) in rules_missing:
        warning('Security group {} does not allow SSH access, you will not be able to ssh into your servers'.format(
            sg_name))

    if ('tcp', POSTGRES_PORT) in rules_missing:
        error('Security group {} does not allow inbound TCP traffic on the default Postgres port {}}'.format(
            sg_name, POSTGRES_PORT
        ))

    check_s3_bucket(variables['wal_s3_bucket'], region)

    return variables


def generate_definition(variables):
    definition_yaml = pystache.render(TEMPLATE, variables)
    return definition_yaml
