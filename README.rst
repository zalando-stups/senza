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


What Senza Solves
=================

AWS CloudFormation is great for managing immutable stacks on
AWS. However, writing CloudFormation templates in JSON format is not
human-friendly, which hinders developer productivity. Also, many parts
of a CloudFormation template are reusable among applications of the
same kind and CloudFormation does not provide a way to reuse
templates. Senza addresses those problems by supporting CloudFormation
templates as YAML input and adding its own 'components' on
top. Components are predefined, easily configurable CloudFormation
snippets that generate all the boilerplate JSON that CloudFormation
requires.


Installation
============

.. code-block:: bash

    $ sudo pip3 install --upgrade stups-senza

Command Line Usage
=====

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

Tip: Use ``senza init`` to quickly bootstrap a new Senza definition YAML for most common use cases (e.g. a web application).

.. code-block:: yaml

    # basic information for generating and executing this definition
    SenzaInfo:
      StackName: kio
      OperatorTopicId: kio-operators
      Parameters:
          - ImageVersion:
              Description: "Docker image version of Kio."

    # a list of senza components to apply to the definition
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

    # just plain Cloud Formation definitions are fully supported:
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

During evaluation, you can mustache templating with access to the rendered definition, including the SenzaInfo,
SenzaComponents and Arguments key (containing all given arguments).


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
