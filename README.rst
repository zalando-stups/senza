=====
Senza
=====

.. image:: https://travis-ci.org/zalando-stups/senza.svg?branch=master
   :target: https://travis-ci.org/zalando-stups/senza

.. image:: https://coveralls.io/repos/zalando-stups/senza/badge.svg
   :target: https://coveralls.io/r/zalando-stups/senza


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

    $ senza create ./my-definition.yaml --region=eu-west-1 1.0

Senza Definition
================

.. code-block:: yaml

    # basic information for generating and executing this definition
    SenzaInfo:
      StackName: kio
      OperatorTopicId: arn:aws:sns:eu-west-1:1234567890:kio-operators
      Parameters:
          - ImageVersion:
              Description: "Docker image version of Kio."

    # a list of senza components to apply to the definition
    SenzaComponents:

      # this basic configuration is required for the other components
      - Configuration:
          Type: Senza::StupsAutoConfiguration

      # will create a launch configuration and auto scaling group with scaling triggers
      - AppServer:
          Type: Senza::TaupageAutoScalingGroup
          InstanceType: t2.micro
          SecurityGroups:
            - app-kio
          ElasticLoadBalancer: AppLoadBalancer
          TaupageConfig:
            runtime: Docker
            source: stups/kio:{{Arguments.ImageVersion}}
            ports:
              8080: 8080
            environment:
              HTTP_CORS_ORIGIN: "*.example.com"
              PGSSLMODE: verify-full
              DB_SUBNAME: "//kio.example.eu-west-1.rds.amazonaws.com:5432/kio?ssl=true"
              DB_USER: kio
              DB_PASSWORD: aws:kms:abcdef1234567890abcdef=

      # creates an ELB entry and Route53 domains to this ELB
      - AppLoadBalancer:
          Type: Senza::WeightedDnsElasticLoadBalancer
          HTTPPort: 8080
          SSLCertificateId: kio-example-com
          HealthCheckPath: /ui/
          SecurityGroups:
              - app-kio-lb

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

Components
==========

* Senza::Configuration
* Senza::StupsAutoConfiguration
* Senza::AutoScalingGroup
* Senza::TaupageAutoScalingGroup
* Senza::ElasticLoadBalancer
* Senza::WeightedDnsElasticLoadBalancer

Unit Tests
==========

.. code-block:: bash

    $ python3 setup.py test --cov-html=true

