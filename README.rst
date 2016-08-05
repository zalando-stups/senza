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


Senza is a command line tool for generating and executing `AWS
CloudFormation`_ templates in a sane way. It supports CloudFormation
templates as YAML input and adds own 'components' on top. Components
are predefined CloudFormation snippets that are easy to configure and
generate all the boilerplate JSON that is required by CloudFormation.

Why Senza
=========

AWS CloudFormation is a great service to manage immutable stacks on
AWS. Although writing CloudFormation in JSON format is not human
friendly and many parts of a CloudFormation template are reusable
among applications of the same kind. CloudFormation itself does not
provide ways to solve those problems hurting developer productivity
and consistency among deployed stacks.

Senza enables you to write CloudFormation templates using YAML format,
a more friendly and easy way to write JSON documents. Senza components
makes possible to reuse common application stack solutions such as
load balancing, auto-scaling, IAM role management, and other
configurations.

Senza also goes a step forward providing base CloudFormation templates
for Web Application, Background Application, Postgres, `Redis`_ Cluster,
and Amazon `Elasticache`_ stack types.


Installation
============

.. code-block:: bash

    $ sudo pip3 install --upgrade stups-senza

Usage
=====

.. code-block:: bash

    $ senza init my-definition.yaml # bootstrap a new app
    $ senza create ./my-definition.yaml 1 1.0

Please read the `STUPS documentation on Senza`_ to learn more.


Senza Definition
================

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

See the `STUPS documentation on Senza`_ for details.

.. _STUPS documentation on Senza: http://stups.readthedocs.org/en/latest/components/senza.html

Unit Tests
==========

.. code-block:: bash

    $ python3 setup.py test --cov-html=true

Releasing
=========

.. code-block:: bash

    $ ./release.sh <NEW-VERSION>

.. _`AWS CloudFormation`: https://aws.amazon.com/cloudformation/
.. _`Elasticache`: https://aws.amazon.com/elasticache/
.. _`Redis`: http://redis.io/
