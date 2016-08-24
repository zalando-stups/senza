=====
Senza
=====

.. image:: https://travis-ci.org/zalando-stups/senza.svg?branch=master
   :target: https://travis-ci.org/zalando-stups/senza
   :alt: Build Status

.. image:: https://coveralls.io/repos/zalando-stups/senza/badge.svg
   :target: https://coveralls.io/r/zalando-stups/senza
   :alt: Code Coverage

.. image:: https://img.shields.io/pypi/dw/stups-senza.svg
   :target: https://pypi.python.org/pypi/stups-senza/
   :alt: PyPI Downloads

.. image:: https://img.shields.io/pypi/v/stups-senza.svg
   :target: https://pypi.python.org/pypi/stups-senza/
   :alt: Latest PyPI version

.. image:: https://img.shields.io/pypi/l/stups-senza.svg
   :target: https://pypi.python.org/pypi/stups-senza/
   :alt: License


Senza is a command line tool that enables you to generate and execute
`AWS CloudFormation`_ templates in a sane, simple way. With Senza, you
can write YAML documents and reuse common application stack solutions
such as load balancing, auto-scaling, IAM role management, and other
configurations. Senza also provides base CloudFormation templates for
web applications, background applications, PostgreSQL, `Redis`_
clusters, and Amazon `ElastiCache`_ stack types.

.. contents::
    :local:
    :depth: 3
    :backlinks: none


What Senza Solves
=================

AWS CloudFormation is great for managing immutable stacks on
AWS. However, writing CloudFormation templates in JSON format is not
human-friendly, which hinders developer productivity. Also, many parts
of a CloudFormation template are reusable among applications of the
same kind and CloudFormation does not provide a way to reuse
templates. 

Senza addresses these problems by supporting CloudFormation
templates as YAML input and adding its own 'components' on
top. Components are predefined, easily configurable CloudFormation
snippets that generate all the boilerplate JSON that CloudFormation
requires.


Installation
============

.. code-block:: bash

    $ sudo pip3 install --upgrade stups-senza

Command Line Usage
==================

You can easily bootstrap Senza definitions to get started quickly:

.. code-block:: bash

    $ senza init my-definition.yaml # bootstrap a new app
    $ senza create ./my-definition.yaml 1 1.0

Create CloudFormation stacks from Senza definitions with the ``create`` command:

.. code-block:: bash

    $ senza create myapp.yaml 1 0.1-SNAPSHOT

How to disable the automatic CloudFormation rollback-on-failure to do 'post-mortem' debugging (e.g. on an EC2 instance):

.. code-block:: bash

    $ senza create --disable-rollback myerroneous-stack.yaml 1 0.1-SNAPSHOT

To pass parameters from a .yaml file:

.. code-block:: bash

    $ senza create --parameter-file parameters.yaml myapp.yaml 1 0.1-SNAPSHOT

To list stacks, use the ``list`` command:

.. code-block:: bash

    $ senza list myapp.yaml         # list only active stacks for myapp
    $ senza list myapp.yaml --all   # list stacks for myapp (also deleted ones)
    $ senza list                    # list all active stacks
    $ senza list --all              # list all stacks (including deleted ones)
    $ senza list "suite-.*" 1       # list stacks starting with "suite" and with version "1"
    $ senza list ".*" 42            # list all stacks  with version "42"
    $ senza list mystack ".*test"  # list all stacks for "mystack" with version ending in "test"

If you want more detailed information about your stacks, Senza provides additional commands:

.. code-block:: bash

    $ senza resources myapp.yaml 1 # list all CF resources
    $ senza events myapp.yaml 1    # list all CF events
    $ senza instances myapp.yaml 1 # list EC2 instances and IPs
    $ senza console myapp.yaml 1   # get EC2 console output for all stack instances
    $ senza console 172.31.1.2     # get EC2 console output for single instance

Most commands take so-called `STACK_REF` arguments. You can either use an
existing Senza definition YAML file (as shown above) or use the stack's name
and version. You can also use regular expressions to match multiple
applications and versions:

.. code-block:: bash

    $ senza inst                    # all instances, no STACK_REF argument given
    $ senza inst mystack            # list instances for all versions of "mystack"
    $ senza inst mystack 1          # only list instances for "mystack" version "1"
    $ senza inst "suite-.*" 1       # list instances starting with "suite" and with version "1"
    $ senza inst ".*" 42            # list all instances  with version "42"
    $ senza inst mystack ".*test"  # list all instances for "mystack" with version ending in "test"

.. Tip::

    All commands and subcommands can be abbreviated, i.e. the following lines are equivalent:

    .. code-block:: bash

        $ senza list
        $ senza l
  

Routing Traffic
---------------

Traffic can be routed via Route53 DNS to your new stack:

.. code-block:: bash

    $ senza traffic myapp.yaml      # show traffic distribution
    $ senza traffic myapp.yaml 2 50 # give version 2 50% of traffic

.. WARNING::
   Some clients use connection pools that - by default - reuse connections as long as there are requests to be processed. In such cases, ``senza traffic`` won't result in any redirection of the traffic, unfortunately. To force such clients to switch traffic from one stack to the other, you might want to manually disable the load balancer (ELB) of the old stack — for example, by changing the ELB listener port. This switches traffic entirely. Switching traffic slowly (via weighted DNS records) is only possible for NEW connections.

   We recommend monitoring clients' behavior when traffic switching, and — if necessary — asking them to reconfigure their connection pools.

Deleting Old Stacks
-------------------

To delete stacks that you're no longer using:

.. code-block:: bash

    $ senza delete myapp.yaml 1
    $ senza del mystack          # shortcut: delete the only version of "mystack"


Bash Completion
---------------

Bash's programmable completion feature permits typing a partial command, then pressing the :kbd:`[Tab]` key to autocomplete the command sequence. If multiple completions are possible, then :kbd:`[Tab]` lists them all.

To activate bash completion for the Senza CLI, just run:

.. code-block:: bash

    $ eval "$(_SENZA_COMPLETE=source senza)"

Put the eval line into your :file:`.bashrc`:

.. code-block:: bash

    $ echo 'eval "$(_SENZA_COMPLETE=source senza)"' >> ~/.bashrc


Controlling Command Output
--------------------------

The Senza CLI supports three different output formats:

``text``
    Default ANSI-colored output for human users.
``json``
    JSON output of tables for scripting.
``tsv``
    Print tables as `tab-separated values (TSV)`_.

JSON is best for handling the output programmatically via various languages or with `jq`_ (a command-line JSON processor). The text format is easy for humans to read, and "tsv" format works well with traditional Unix text processing tools like sed, grep, and awk:

.. _tab-separated values (TSV): https://en.wikipedia.org/wiki/Tab-separated_values
.. code-block:: bash

    $ senza list --output json | jq .
    $ senza instances my-stack --output tsv | awk -F\\t '{ print $6 }'

.. _senza-definition:

Senza Definition
================

A minimal Senza definition without any Senza components would look like:

.. code-block:: yaml

    Description: "A minimal Cloud Formation stack creating a SQS queue"
    SenzaInfo:
      StackName: example
    Resources:
      MyQueue:
        Type: AWS::SQS::Queue

**Tip**: Use ``senza init`` to quickly bootstrap a new Senza definition YAML for most common use cases (e.g. a web application).

The SenzaInfo Key
----------------

The ``SenzaInfo`` key configures global Senza behavior and must always be present in the definition YAML. Available properties for the ``SenzaInfo`` section:

``StackName``
    The stack name (required).
``OperatorTopicId``
    Optional SNS topic name or ARN for CloudFormation notifications. As an example: You can use this to send notifications about deployments to a mailing list.
``Parameters``
    Custom Senza definition parameters. Use to dynamically substitute variables in the CloudFormation template.
    
.. code-block:: yaml

    # basic information for generating and executing this definition
    SenzaInfo:
      StackName: kio
      OperatorTopicId: kio-operators
      Parameters:
          - ImageVersion:
              Description: "Docker image version of Kio."

    # a list of Senza components to apply to the definition
    SenzaComponents:
      - Configuration:
          Type: Senza::StupsAutoConfiguration # auto-detect network setup
      # will create a launch configuration and auto scaling group with min/max=1
      - AppServer:
          Type: Senza::TaupageAutoScalingGroup
          InstanceType: t2.micro
          SecurityGroups: [app-kio] # can be either name or id ("sg-..")
          ElasticLoadBalancer: AppLoadBalancer
          TaupageConfig:
            runtime: Docker
            source: stups/kio:{{Arguments.ImageVersion}}
            ports:
              8080: 8080
            environment:
              PGSSLMODE: verify-full
              DB_SUBNAME: "//kio.example.eu-west-1.rds.amazonaws.com:5432/kio?ssl=true"
              DB_USER: kio
              DB_PASSWORD: aws:kms:abcdef1234567890abcdef=
      # creates an ELB entry and Route53 domains to this ELB
      - AppLoadBalancer:
          Type: Senza::WeightedDnsElasticLoadBalancer
          HTTPPort: 8080
          HealthCheckPath: /ui/
          SecurityGroups: [app-kio-lb]
          Scheme: internet-facing

    # Plain CloudFormation definitions are fully supported:
    Outputs:
      URL:
        Description: "The ELB URL of the new Kio deployment."
        Value:
          "Fn::Join":
            - ""
            -
              - "http://"
              - "Fn::GetAtt":
                  - AppLoadBalancer
                  - DNSName

During evaluation, you can do mustache templating with access to the rendered definition, including the `SenzaInfo`, `SenzaComponents` and `Arguments` keys (containing all given arguments).

You can also specify the parameters by name, which makes the Senza CLI more readable. This might come handy in
complex scenarios with sizeable number of parameters:

.. code-block:: bash
    $ senza create example.yaml 3 example MintBucket=<mint-bucket> ImageVersion=latest

Here, the ``ApplicationId`` is given as a positional parameter. The two
other parameters follow, specified by their names. The named parameters on the
command line can be given in any order, but no positional parameter is allowed
to follow the named ones.

.. Note::

   The ``name=value`` named parameters are split on the first ``=``, so you can still include a literal ``=`` in the value part. Just pass this parameter with the name, to prevent Senza from treating the part of the parameter value before the first ``=`` as the parameter name.

You can pass any of the supported `CloudFormation Properties <http://
docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/
parameters-section-structure.html>`_ such as ``AllowedPattern``, ``AllowedValues``,
``MinLength``, ``MaxLength``, etc. Senza itself will not enforce these,
but CloudFormation will evaluate the generated template and raise an exception
if any of the properties are not met. For example:

.. code-block:: bash

    $ senza create example.yaml 3 example latest mint-bucket "Way too long greeting"
    Generating Cloud Formation template.. OK
    Creating Cloud Formation stack hello-world-3.. EXCEPTION OCCURRED: An error occurred (ValidationError) when calling the CreateStack operation: Parameter 'GreetingText' must contain at most 15 characters
    Traceback (most recent call last):
    [...]

Using the ``Default`` attribute, you can give any parameter a default value.
If a parameter was not specified on the command line (either as positional or
named), the default value is used. We suggest putting all default-value
parameters at the bottom of your parameter definition list. Otherwise, there will be no way to map them to
proper positions, and you'll have to specify all the following
parameters using a ``name=value``.

There is an option to pass parameters from a file (the file needs to be formatted in .yaml):

.. code-block:: bash

    $ senza create --parameter-file parameters.yaml example.yaml 3 1.0-SNAPSHOT

An example of a parameter file:

.. code-block:: yaml

   ApplicationId: example-app-id
   MintBucket: your-mint-bucket

You can also combine parameter files and parameters from the command line, but you can't name the same parameter twice. Also, the parameter can't exist both in a file and on the command line:

.. code-block:: bash

    $ senza create --parameter-file parameters.yaml example.yaml 3 1.0-SNAPSHOT Param=Example1

AccountInfo
===========

Senza templates offer the following properties:

``{{AccountInfo.Region}}``: the AWS region where the stack is created. Ex: 'eu-central-1'. In many parts of a template, you can also use `{"Ref" : "AWS::Region"}`.

``{{AccountInfo.AccountAlias}}``: the alias name of the AWS account. Ex: 'super-team1-account'.

``{{AccountInfo.AccountID}}``: the AWS account id. Ex: '353272323354'.

``{{AccountInfo.TeamID}}``: the team ID. Ex: 'super-team1'.

``{{AccountInfo.Domain}}``: the AWS account domain. Ex: 'super-team1.net'.

Mappings
================

Senza mappings are essentially key-value pairs, and behave just like `CloudFormation mappings <http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/mappings-section-structure.html>`_. Use mappings for ``Images``, ``ServerSubnets`` or ``LoadBalancerSubnets``. 

An example:

.. code-block:: yaml

   Mappings:
      Images:
         eu-west-1:
            MyImage: "ami-123123"
   # (..)
   Image: MyImage

Senza Components
================

Configure all your Senza components in a list below the top-level `SenzaComponents` key. The structure is as follows:

.. code-block:: yaml

    SenzaComponents:
      - ComponentName1:
          Type: ComponentType1
          SomeComponentProperty: "some value"
      - ComponentName2:
          Type: ComponentType2

.. Note::

    Each list item below `SenzaComponents` is a map with only one key (the component name).
    The YAML "flow-style" syntax would be: ``SenzaComponents: [{CompName: {Type: CompType}}]``.


AutoScaling
===========

``AutoScaling`` properties include:

``Minimum``
    Minimum number of instances to spawn.
``Maximum``
    Maximum number of instances to spawn.
``SuccessRequires``:
    During startup of the stack, it defines when CloudFormation considers your ASG healthy. Defaults to one healthy instance/15 minutes. You can change settings — for example, "four healthy instances/1:20:30" would look like "4 within 1h20m30s". You can omit hours/minutes/seconds as you please. Values that look like integers will be counted as healthy instances: for example, "2" is interpreted as two healthy instances within the default timeout of 15 minutes.
``MetricType``
    Metric for doing auto-scaling that creates automatic alarms in CloudWatch for you. Must be either ``CPU``, ``NetworkIn`` or ``NetworkOut``. If you don't supply any info, your auto-scaling group will not dynamically scale and you'll have to define your own alerts.
``ScaleUpThreshold``
    The upper scaling threshold of the metric value. For the "CPU" metric: a value of 70 means 70% CPU usage. For network metrics, a value of 100 means 100 bytes. You can pass the unit (KB/GB/TB), e.g. "100 GB".
``ScaleDownThreshold``
    The lower scaling threshold of the metric value. For the "CPU" metric: a value of 40 means 40% CPU usage. For network metrics, a value of 2 means 2 bytes. You can pass the unit (KB/GB/TB), e.g. "2 GB".
``ScalingAdjustment``
    Number of instances added/removed per scaling action. Defaults to 1.
``Cooldown``:
    After a scaling action occurs, do not scale again for this amount of time (in seconds). Defaults to 60 (one minute).
``Statistic``
    Which statistic to track when deciding your scaling thresholds are met. Defaults to "Average", but can also be "SampleCount", "Sum", "Minimum", "Maximum".
``Period``
    Period (in seconds) over which statistic is calculated. Defaults to 300 (five minutes).
``EvaluationPeriods``
    The number of periods over which data is compared to the specified threshold. Defaults to 2.

BlockDeviceMappings & Ebs Properties
================================================

``BlockDeviceMappings`` properties are ``DeviceName`` (for example, /dev/xvdk) and ``Ebs`` (map of EBS options). ``VolumeSize``, an ``Ebs`` property, is for determining how much GB an EBS should have.

WeightedDnsElasticLoadBalancer
================================

Senza's **WeightedDnsElasticLoadBalancer** component type creates one HTTPs ELB resource with Route 53 weighted domains.
You can either auto-detect the SSL certificate name used by the ELB, or name it ``SSLCertificateId``. Specify the main domain (``MainDomain``) or the default Route53 hosted zone will apply. 

An internal load balancer is created by default, which differs from AWS's default behavior. To create an Internet-facing ELB, explicitly set the ``Scheme`` to ``internet-facing``.

.. code-block:: yaml

    SenzaComponents:
      - AppLoadBalancer:
          Type: Senza::WeightedDnsElasticLoadBalancer
          HTTPPort: 8080
          SecurityGroups:
            - app-myapp-lb

The WeightedDnsElasticLoadBalancer component supports the following configuration properties:

``HTTPPort``
    The HTTP port used by the EC2 instances.
``HealthCheckPath``
    The HTTP path to use for health checks, e.g. "/health". Must return 200.
``HealthCheckPort``
    Optional. Port used for the health check. Defaults to ``HTTPPort``.
``SecurityGroups``
    List of security groups to use for the ELB. The security groups must allow SSL traffic.
``MainDomain``
    Main domain to use, e.g. "myapp.example.org".
``VersionDomain``
    Version domain to use, e.g. "myapp-1.example.org". You can use the usual templating feature to integrate the stack version, e.g. ``myapp-{{SenzaInfo.StackVersion}}.example.org``.
``Scheme``
    The load balancer scheme. Either ``internal`` or ``internet-facing``. Defaults to ``internal``.
``SSLCertificateId``
    Name or ARN ID of the uploaded SSL/TLS server certificate to use, e.g. ``myapp-example-org-letsencrypt`` or ``arn:aws:acm:eu-central-1:123123123:certificate/abcdefgh-ijkl-mnop-qrst-uvwxyz012345``.
    You can check available IAM server certificates with :code:`aws iam list-server-certificates`. For ACM certificates, use :code:`aws acm list-certificates`.

Additionally, you can specify any of the `valid AWS CloudFormation ELB properties`_ (e.g. to overwrite ``Listeners``).

.. _valid AWS CloudFormation ELB properties: http://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/aws-properties-ec2-elb.html

Cross-Stack References
======================

Traditional CloudFormation templates only allow you to reference resources located in the same template. This can be
quite limiting. To compensate, Senza selectively supports special *cross-stack references* in some parts of your template — for instance, in `SecurityGroups` and `IamRoles`:

.. code-block:: yaml

   AppServer:
      Type: Senza::TaupageAutoScalingGroup
      InstanceType: c4.xlarge
      SecurityGroups:
        - Stack: base-1
          LogicalId: ApplicationSecurityGroup
      IamRoles:
        - Stack: base-1
          LogicalId: ApplicationRole

With these references, you can have an additional special stack per application that defines common security groups and IAM roles shared across different versions. Note that this in contrast to using `senza init`.


Unit Tests
==========

.. code-block:: bash

    $ python3 setup.py test --cov-html=true

Releasing
=========

.. code-block:: bash

    $ ./release.sh <NEW-VERSION>

.. _`AWS CloudFormation`: https://aws.amazon.com/cloudformation/
.. _`ElastiCache`: https://aws.amazon.com/elasticache/
.. _`Redis`: http://redis.io/
