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


Senza is a command line tool for generating and executing AWS Cloud Formation templates in a sane way. It supports
Cloud Formation templates as YAML input and adds own 'components' on top. Components are predefined Cloud Formation
snippets that are easy to configure and generate all the boilerplate JSON that is required by Cloud Formation.

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

