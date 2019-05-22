import click
import pytest
import responses
from mock import MagicMock

from senza.spotinst import MissingSpotinstAccount
from senza.components.elastigroup import (component_elastigroup, ELASTIGROUP_DEFAULT_PRODUCT,
                                          ELASTIGROUP_DEFAULT_STRATEGY, resolve_account_id, SPOTINST_API_URL,
                                          extract_block_mappings,
                                          extract_auto_scaling_rules, ensure_instance_monitoring,
                                          ensure_default_strategy, extract_autoscaling_capacity,
                                          ensure_default_product, fill_standard_tags, extract_subnets,
                                          extract_load_balancer_name, extract_public_ips,
                                          extract_image_id, extract_security_group_ids, extract_instance_types,
                                          extract_instance_profile)


def test_component_elastigroup_defaults(monkeypatch):
    configuration = {
        "Name": "eg1",
        "SecurityGroups": "sg1",
        "InstanceType": "big",
        "SpotAlternatives": [
            "smaller",
            "small",
            "small-ish"
        ]
    }
    args = MagicMock()
    args.region = "reg1"
    info = {'StackName': 'foobar', 'StackVersion': '0.1', 'SpotinstAccessToken': 'token1'}
    subnets = ["sn1", "sn2", "sn3"]
    server_subnets = {"reg1": {"Subnets": subnets}}
    senza = {"Info": info}
    mappings = {"Senza": senza, "ServerSubnets": server_subnets}
    definition = {"Resources": {}, "Mappings": mappings}
    mock_sg = MagicMock()
    mock_sg.return_value = "sg1"
    monkeypatch.setattr('senza.aws.resolve_security_group', mock_sg)

    mock_resolve_account_id = MagicMock()
    mock_resolve_account_id.return_value = 'act-12345abcdef'
    monkeypatch.setattr('senza.components.elastigroup.resolve_account_id', mock_resolve_account_id)

    mock_account_info = MagicMock()
    mock_account_info.Region = "reg1"
    mock_account_info.AccountID = "12345"

    result = component_elastigroup(definition, configuration, args, info, False, mock_account_info)

    properties = result["Resources"]["eg1"]["Properties"]
    assert properties["accountId"] == 'act-12345abcdef'
    assert properties["group"]["capacity"] == {"target": 1, "minimum": 1, "maximum": 1}
    instance_types = properties["group"]["compute"]["instanceTypes"]
    assert instance_types["ondemand"] == "big"
    assert instance_types["spot"] >= ["smaller", "small", "small-ish"]
    launch_specification = properties["group"]["compute"]["launchSpecification"]
    assert launch_specification["monitoring"]
    assert launch_specification["securityGroupIds"] == ["sg1"]
    tags = launch_specification["tags"]
    assert {'tagKey': 'Name', 'tagValue': 'foobar-0.1'} in tags
    assert {'tagKey': 'StackName', 'tagValue': 'foobar'} in tags
    assert {'tagKey': 'StackVersion', 'tagValue': '0.1'} in tags
    assert properties["group"]["compute"]["product"] == ELASTIGROUP_DEFAULT_PRODUCT
    assert properties["group"]["compute"]["subnetIds"] == {
        "Fn::FindInMap": ["ServerSubnets", {"Ref": "AWS::Region"}, "Subnets"]}
    assert properties["group"]["region"] == "reg1"
    assert properties["group"]["strategy"] == ELASTIGROUP_DEFAULT_STRATEGY

    assert "scaling" in properties["group"]
    assert "scheduling" in properties["group"]
    assert "thirdPartiesIntegration" in properties["group"]


def test_raw_user_data_and_base64_encoding_cf_function_used(monkeypatch):
    configuration = {
        "Name": "eg1",
        "SecurityGroups": {"Ref": "sg1"},
        "InstanceType": "big",
        "TaupageConfig": {
            "runtime": "Docker",
            "source": "some/fake/artifact:test"
        }
    }
    args = MagicMock()
    args.region = "reg1"
    info = {'StackName': 'foobar', 'StackVersion': '0.1', 'SpotinstAccessToken': 'token1'}
    definition = {"Resources": {},
                  "Mappings": {"Senza": {"Info": info}, "ServerSubnets": {"reg1": {"Subnets": ["sn1", "sn2", "sn3"]}}}}

    mock_resolve_account_id = MagicMock()
    mock_resolve_account_id.return_value = 'act-12345abcdef'
    monkeypatch.setattr('senza.components.elastigroup.resolve_account_id', mock_resolve_account_id)

    result = component_elastigroup(definition, configuration, args, info, True, MagicMock())

    launch_specification = result["Resources"]["eg1"]["Properties"]["group"]["compute"]["launchSpecification"]
    assert "some/fake/artifact:test" in launch_specification["userData"]["Fn::Base64"]


def test_missing_access_token():
    with pytest.raises(click.UsageError):
        component_elastigroup({}, {}, MagicMock(), MagicMock(), False, MagicMock())


def test_spotinst_account_resolution():
    with responses.RequestsMock() as rsps:
        rsps.add(rsps.GET, '{}/setup/account?awsAccountId=12345'.format(SPOTINST_API_URL), status=200,
                 json={"response": {
                     "items": [
                         {"accountId": "act-1234abcd", "name": "expected-match"},
                         {"accountId": "act-xyz", "name": "second-match"}
                     ],
                 }})

        account_id = resolve_account_id("fake-token", "12345")
        assert account_id == "act-1234abcd"


def test_spotinst_account_resolution_failure():
    with responses.RequestsMock() as rsps:
        rsps.add(rsps.GET, '{}/setup/account?awsAccountId=12345'.format(SPOTINST_API_URL), status=200,
                 json={"response": {
                     "items": [],
                 }})

        with pytest.raises(MissingSpotinstAccount):
            resolve_account_id("fake-token", "12345")


def test_block_mappings():
    test_cases = [
        {  # leave elastigroup settings untouched
            "input": {},
            "given_config": {},
            "expected_config": {}
        },
        {  # leave elastigroup blockDeviceMappings untouched
            "input": {},
            "given_config": {"compute": {"launchSpecification": {"blockDeviceMappings": {"foo": "bar"}}}},
            "expected_config": {"compute": {"launchSpecification": {"blockDeviceMappings": {"foo": "bar"}}}},
        },
        {  # Keep Spotinst defs when there are Senza defs
            "input": {"BlockDeviceMappings": [{"DeviceName": "/dev/sda1"}]},
            "given_config": {"compute": {"launchSpecification": {"blockDeviceMappings": {"foo": "bar"}}}},
            "expected_config": {"compute": {"launchSpecification": {"blockDeviceMappings": {"foo": "bar"}}}},
        },
        {  # convert Senza defs to Spotinst
            "input": {"BlockDeviceMappings": [{"DeviceName": "/dev/sda1", "Ebs": {"VolumeSize": 42}}]},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {"blockDeviceMappings": [{
                "deviceName": "/dev/sda1",
                "ebs": {
                    "deleteOnTermination": True,
                    "volumeType": "gp2",
                    "volumeSize": 42
                }
            }]}}},
        },
    ]

    for test_case in test_cases:
        got = test_case["given_config"]
        extract_block_mappings(test_case["input"], got)
        assert test_case["expected_config"] == got


def test_auto_scaling_rules():
    test_cases = [
        {  # leave elastigroup settings untouched
            "input": {},
            "given_config": {},
            "expected_config": {"scaling": {}}
        },
        {  # leave elastigroup scaling section untouched
            "input": {},
            "given_config": {"compute": {}, "scaling": {"down": {}, "up": {}}},
            "expected_config": {"compute": {}, "scaling": {"down": {}, "up": {}}},
        },
        {  # Keep Spotinst defs when there are Senza defs
            "input": {"AutoScaling": {"ScaleUpThreshold": 42, "ScalingAdjustment": 9, "Cooldown": 42}},
            "given_config": {"compute": {}, "scaling": {}},
            "expected_config": {"compute": {}, "scaling": {}},
        },
        {  # convert Senza defs with scale up only
            "input": {
                "AutoScaling": {
                    "ScaleUpThreshold": 42,
                    "ScalingAdjustment": 9,
                    "Cooldown": 42
                }
            },
            "given_config": {},
            "expected_config": {"scaling": {
                "up": [{
                    "policyName": "Scale if CPU >= 42 percent for 10.0 minutes (average)",
                    "metricName": "CPUUtilization",
                    "statistic": "average",
                    "unit": "percent",
                    "threshold": 42,
                    "namespace": "AWS/EC2",
                    "dimensions": [{"name": "InstanceId"}],
                    "period": 300,
                    "evaluationPeriods": 2,
                    "cooldown": 42,
                    "action": {"type": "adjustment", "adjustment": 9},
                    "operator": "gte"
                }]
            }},
        },
        {  # convert Senza defs with scale down network
            "input": {
                "AutoScaling": {
                    "ScaleDownThreshold": "42 GB",
                    "Period": 60,
                    "EvaluationPeriods": 1,
                    "ScalingAdjustment": 9,
                    "MetricType": "NetworkIn"
                }
            },
            "given_config": {},
            "expected_config": {"scaling": {
                "down": [{
                    "policyName": "Scale if NetworkIn < 42 Gigabytes for 1.0 minutes (average)",
                    "metricName": "NetworkIn",
                    "statistic": "average",
                    "unit": "Gigabytes",
                    "threshold": "42",
                    "namespace": "AWS/EC2",
                    "dimensions": [{"name": "InstanceId"}],
                    "period": 60,
                    "evaluationPeriods": 1,
                    "cooldown": 60,
                    "action": {"type": "adjustment", "adjustment": 9},
                    "operator": "lt"
                }]
            }},
        },
    ]

    for test_case in test_cases:
        got = test_case["given_config"]
        extract_auto_scaling_rules(test_case["input"], got)
        assert test_case["expected_config"] == got


def test_detailed_monitoring():
    test_cases = [
        {  # set default monitoring option
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {"monitoring": True}}}
        },
        {  # leave monitoring untouched
            "given_config": {"compute": {"launchSpecification": {"monitoring": "fake"}}},
            "expected_config": {"compute": {"launchSpecification": {"monitoring": "fake"}}}
        },
    ]
    for test_case in test_cases:
        got = test_case["given_config"]
        ensure_instance_monitoring(got)
        assert test_case["expected_config"] == got


def test_prediction_strategy():
    test_cases = [
        {  # default prediction strategy
            "given_config": {},
            "expected_config": {"strategy": ELASTIGROUP_DEFAULT_STRATEGY}
        },
        {  # leave strategy untouched
            "given_config": {"strategy": "fake"},
            "expected_config": {"strategy": "fake"}
        },
    ]
    for test_case in test_cases:
        got = test_case["given_config"]
        ensure_default_strategy(got)
        assert test_case["expected_config"] == got


def test_autoscaling_capacity():
    test_cases = [
        {  # default prediction strategy
            "input": {},
            "given_config": {},
            "expected_config": {"capacity": {"target": 1, "minimum": 1, "maximum": 1}}
        },
        {  # leave strategy untouched
            "input": {"AutoScaling": {"DesiredCapacity": 42}},
            "given_config": {"capacity": "fake"},
            "expected_config": {"capacity": "fake"}
        },
        {  # convert senza capacity
            "input": {"AutoScaling": {"DesiredCapacity": 42, "Maximum": 69}},
            "given_config": {},
            "expected_config": {"capacity": {"target": 42, "minimum": 1, "maximum": 69}}
        },
        {  # convert senza capacity and adjust desired to min
            "input": {"AutoScaling": {"DesiredCapacity": 1, "Minimum": 2, "Maximum": 42}},
            "given_config": {},
            "expected_config": {"capacity": {"target": 2, "minimum": 2, "maximum": 42}}
        },
        {  # convert senza capacity and adjust desired to max
            "input": {"AutoScaling": {"DesiredCapacity": 69, "Minimum": 2, "Maximum": 42}},
            "given_config": {},
            "expected_config": {"capacity": {"target": 42, "minimum": 2, "maximum": 42}}
        },
    ]
    for test_case in test_cases:
        got = test_case["given_config"]
        extract_autoscaling_capacity(test_case["input"], got)
        assert test_case["expected_config"] == got


def test_product():
    test_cases = [
        {  # default product
            "given_config": {},
            "expected_config": {"compute": {"product": ELASTIGROUP_DEFAULT_PRODUCT}},
        },
        {  # leave product untouched
            "given_config": {"compute": {"product": "fake"}},
            "expected_config": {"compute": {"product": "fake"}},
        },
    ]
    for test_case in test_cases:
        got = test_case["given_config"]
        ensure_default_product(got)
        assert test_case["expected_config"] == got


def test_standard_tags():
    test_cases = [
        {  # default tags
            "definition": {"Mappings": {"Senza": {"Info": {"StackName": "foo", "StackVersion": "bar"}}}},
            "given_config": {},
            "expected_config": {
                "compute": {
                    "launchSpecification": {
                        "tags": [
                            {"tagKey": "Name", "tagValue": "foo-bar"},
                            {"tagKey": "StackName", "tagValue": "foo"},
                            {"tagKey": "StackVersion", "tagValue": "bar"},
                        ]
                    },
                },
                "name": "foo-bar",
            },
        },
        {  # add standard tags if custom tags specified
            "definition": {"Mappings": {"Senza": {"Info": {"StackName": "foo", "StackVersion": "bar"}}}},
            "given_config": {"compute": {"launchSpecification": {
                "tags": [{"tagKey": "some-key", "tagValue": "some-value"}]}}
            },
            "expected_config": {
                "compute": {
                    "launchSpecification": {
                        "tags": [
                            {"tagKey": "some-key", "tagValue": "some-value"},
                            {"tagKey": "Name", "tagValue": "foo-bar"},
                            {"tagKey": "StackName", "tagValue": "foo"},
                            {"tagKey": "StackVersion", "tagValue": "bar"},
                        ]
                    },
                },
                "name": "foo-bar",
            },
        },
        {  # should not override standard tags
            "definition": {"Mappings": {"Senza": {"Info": {"StackName": "foo", "StackVersion": "bar"}}}},
            "given_config": {
                "compute": {
                    "launchSpecification": {
                        "tags": [
                            {"tagKey": "Name", "tagValue": "some-name"},
                            {"tagKey": "StackName", "tagValue": "some-stack-version"},
                            {"tagKey": "StackVersion", "tagValue": "some-stack-version"}
                        ]
                    }
                }
            },
            "expected_config": {
                "compute": {
                    "launchSpecification": {
                        "tags": [
                            {"tagKey": "Name", "tagValue": "foo-bar"},
                            {"tagKey": "StackName", "tagValue": "foo"},
                            {"tagKey": "StackVersion", "tagValue": "bar"},
                        ]
                    },
                },
                "name": "foo-bar",
            },
        },
        {  # leave name untouched
            "definition": {"Mappings": {"Senza": {"Info": {"StackName": "foo", "StackVersion": "bar"}}}},
            "given_config": {"name": "must-stay-untouched"},
            "expected_config": {
                "compute": {
                    "launchSpecification": {
                        "tags": [
                            {"tagKey": "Name", "tagValue": "foo-bar"},
                            {"tagKey": "StackName", "tagValue": "foo"},
                            {"tagKey": "StackVersion", "tagValue": "bar"},
                        ],
                    },
                },
                "name": "must-stay-untouched",
            },
        },
    ]
    for test_case in test_cases:
        got = test_case["given_config"]
        fill_standard_tags(test_case["definition"], got)
        assert test_case["expected_config"] == got


def test_extract_subnets():
    test_cases = [
        {  # use auto discovered server subnets
            "component_config": {},
            "given_config": {},
            "expected_config": {
                "compute": {"subnetIds": {"Fn::FindInMap": ["ServerSubnets", {"Ref": "AWS::Region"}, "Subnets"]}},
                "region": "reg1"},
        },
        {  # use auto discovered DMZ subnets
            "component_config": {"AssociatePublicIpAddress": True},
            "given_config": {},
            "expected_config": {
                "compute": {"subnetIds": {"Fn::FindInMap": ["LoadBalancerSubnets", {"Ref": "AWS::Region"}, "Subnets"]}},
                "region": "reg1"},
        },
        {  # leave subnetIds untouched
            "component_config": {},
            "given_config": {"compute": {"subnetIds": ["subnet01"]}},
            "expected_config": {"compute": {"subnetIds": ["subnet01"]}, "region": "reg1"},
        },
    ]
    account_info = MagicMock()
    account_info.Region = "reg1"
    for test_case in test_cases:
        input = test_case["given_config"]
        config = test_case["component_config"]
        extract_subnets(config, input, account_info)
        assert test_case["expected_config"] == input


def test_load_balancers():
    test_cases = [
        {  # no load balancers, default healthcheck
            "input": {},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {"healthCheckType": "EC2",
                                                                    "healthCheckGracePeriod": 300}}},
        },
        {  # no load balancers, Taupage's healthcheck type, default grace period
            "input": {"HealthCheckType": "FAKE"},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {"healthCheckType": "FAKE",
                                                                    "healthCheckGracePeriod": 300}}},
        },
        {  # no load balancers, Taupage's healthcheck type and grace period
            "input": {"HealthCheckType": "FAKE", "HealthCheckGracePeriod": 42},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {"healthCheckType": "FAKE",
                                                                    "healthCheckGracePeriod": 42}}},
        },
        {  # no load balancers, Elastigroup's healthcheck type and default grace period
            "input": {},
            "given_config": {"compute": {"launchSpecification": {"healthCheckType": "EG-FAKE"}}},
            "expected_config": {"compute": {"launchSpecification": {"healthCheckType": "EG-FAKE",
                                                                    "healthCheckGracePeriod": 300}}},
        },
        {  # no load balancers, Elastigroup's healthcheck type and grace period
            "input": {},
            "given_config": {"compute": {"launchSpecification": {"healthCheckType": "EG-FAKE",
                                                                 "healthCheckGracePeriod": 42}}},
            "expected_config": {"compute": {"launchSpecification": {"healthCheckType": "EG-FAKE",
                                                                    "healthCheckGracePeriod": 42}}},
        },
        {  # 1 classic load balancer from Taupage, healthcheck type set to ELB (default grace period)
            "input": {"ElasticLoadBalancer": "foo"},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {
                "loadBalancersConfig": {
                    "loadBalancers": [
                        {"name": {"Ref": "foo"}, "type": "CLASSIC"},
                    ],
                },
                "healthCheckType": "ELB",
                "healthCheckGracePeriod": 300,
            }}},
        },
        {  # multiple classic load balancers from Taupage, healthcheck type set to ELB (default grace period)
            "input": {"ElasticLoadBalancer": ["foo", "bar"]},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {
                "loadBalancersConfig": {
                    "loadBalancers": [
                        {"name": {"Ref": "foo"}, "type": "CLASSIC"},
                        {"name": {"Ref": "bar"}, "type": "CLASSIC"},
                    ],
                },
                "healthCheckType": "ELB",
                "healthCheckGracePeriod": 300,
            }}},
        },
        {  # 1 application load balancer from Taupage, healthcheck type set to TARGET_GROUP (default grace period)
            "input": {"ElasticLoadBalancerV2": "bar"},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {
                "loadBalancersConfig": {
                    "loadBalancers": [
                        {"arn": {"Ref": "barTargetGroup"}, "type": "TARGET_GROUP"},
                    ],
                },
                "healthCheckType": "TARGET_GROUP",
                "healthCheckGracePeriod": 300,
            }}},
        },
        {  # multiple application load balancers from Taupage, healthcheck type set to TARGET_GROUP
            # (default grace period)
            "input": {"ElasticLoadBalancerV2": ["foo", "bar"]},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {
                "loadBalancersConfig": {
                    "loadBalancers": [
                        {"arn": {"Ref": "fooTargetGroup"}, "type": "TARGET_GROUP"},
                        {"arn": {"Ref": "barTargetGroup"}, "type": "TARGET_GROUP"},
                    ],
                },
                "healthCheckType": "TARGET_GROUP",
                "healthCheckGracePeriod": 300,
            }}},
        },
        {  # mixed load balancers from Taupage, healthcheck type set to TARGET_GROUP and custom Taupage grace period
            "input": {
                "ElasticLoadBalancer": "foo",
                "ElasticLoadBalancerV2": "bar",
                "HealthCheckGracePeriod": 42
            },
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {
                "loadBalancersConfig": {
                    "loadBalancers": [
                        {"name": {"Ref": "foo"}, "type": "CLASSIC"},
                        {"arn": {"Ref": "barTargetGroup"}, "type": "TARGET_GROUP"},
                    ],
                },
                "healthCheckType": "TARGET_GROUP",
                "healthCheckGracePeriod": 42,
            }}},
        },
        {  # 1 load balancer from Taupage, healthcheck type and grace period set in Taupage
            "input": {
                "ElasticLoadBalancer": "foo",
                "HealthCheckType": "FAKE",
                "HealthCheckGracePeriod": 42
            },
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {
                "loadBalancersConfig": {
                    "loadBalancers": [
                        {"name": {"Ref": "foo"}, "type": "CLASSIC"},
                    ],
                },
                "healthCheckType": "FAKE",
                "healthCheckGracePeriod": 42,
            }}},
        },
    ]
    for test_case in test_cases:
        got = test_case["given_config"]
        extract_load_balancer_name(test_case["input"], got)
        assert test_case["expected_config"] == got


def test_multiple_target_groups():
    test_cases = [
        {  # multiple target groups in raw ARN form, ignore ALB TG
            "input": {"ElasticLoadBalancerV2": "foo", "TargetGroupARNs": ["bar", "baz"]},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {
                "loadBalancersConfig": {
                    "loadBalancers": [
                        {"arn": "bar", "type": "TARGET_GROUP"},
                        {"arn": "baz", "type": "TARGET_GROUP"},
                    ],
                },
                "healthCheckType": "TARGET_GROUP",
                "healthCheckGracePeriod": 300,
            }}},
        },
        {  # multiple target groups with Ref, ignore ALB TG
            "input": {"ElasticLoadBalancerV2": "foo", "TargetGroupARNs": [{"Ref": "bar"}, {"Ref": "baz"}]},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {
                "loadBalancersConfig": {
                    "loadBalancers": [
                        {"arn": {"Ref": "bar"}, "type": "TARGET_GROUP"},
                        {"arn": {"Ref": "baz"}, "type": "TARGET_GROUP"},
                    ],
                },
                "healthCheckType": "TARGET_GROUP",
                "healthCheckGracePeriod": 300,
            }}},
        },
        {  # ignore Taupage target groups, leave Elatigroup untouched
            "input": {"ElasticLoadBalancerV2": "foo", "TargetGroupARNs": [{"Ref": "bar"}, {"Ref": "baz"}]},
            "given_config": {"compute": {
                "launchSpecification": {
                    "loadBalancersConfig": {
                        "loadBalancers": [
                            {"arn": "givenTargetGroup", "type": "TARGET_GROUP"},
                        ],
                    },
                    "healthCheckType": "TARGET_GROUP",
                    "healthCheckGracePeriod": 300,
                }
            }},
            "expected_config": {"compute": {"launchSpecification": {
                "loadBalancersConfig": {
                    "loadBalancers": [
                        {"arn": "givenTargetGroup", "type": "TARGET_GROUP"},
                    ],
                },
                "healthCheckType": "TARGET_GROUP",
                "healthCheckGracePeriod": 300,
            }}},
        },
    ]
    for test_case in test_cases:
        got = test_case["given_config"]
        extract_load_balancer_name(test_case["input"], got)
        assert test_case["expected_config"] == got


def test_public_ips():
    test_cases = [
        {  # default behavior - no public IPs, leave untouched
            "input": {},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {}}},
        },
        {  # set networkInterfaces when public IP requested in Taupage
            "input": {"AssociatePublicIpAddress": True},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {"networkInterfaces": [{
                "deleteOnTermination": True,
                "deviceIndex": 0,
                "associatePublicIpAddress": True,
            }]}}},
        },
        {  # leave networkInterfaces untouched
            "input": {"AssociatePublicIpAddress": True},
            "given_config": {"compute": {"launchSpecification": {"networkInterfaces": "fake"}}},
            "expected_config": {"compute": {"launchSpecification": {"networkInterfaces": "fake"}}},
        },
    ]
    for test_case in test_cases:
        got = test_case["given_config"]
        extract_public_ips(test_case["input"], got)
        assert test_case["expected_config"] == got


def test_extract_image_id():
    test_cases = [
        {  # default behavior - set latest taupage image
            "input": {},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {
                "imageId": {"Fn::FindInMap": ["Images", {"Ref": "AWS::Region"}, "LatestTaupageImage"]}
            }}},
        },
        {  # leave imageId untouched
            "input": {},
            "given_config": {"compute": {"launchSpecification": {"imageId": "fake-id"}}},
            "expected_config": {"compute": {"launchSpecification": {"imageId": "fake-id"}}},
        },
        {  # use specified image from the Senza mapping
            "input": {"Image": "Foo"},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {
                "imageId": {"Fn::FindInMap": ["Images", {"Ref": "AWS::Region"}, "Foo"]}
            }}},
        }
    ]
    for test_case in test_cases:
        got = test_case["given_config"]
        extract_image_id(test_case["input"], got)
        assert test_case["expected_config"] == got


def test_extract_security_group_ids(monkeypatch):
    test_cases = [
        {  # default behavior - no particular security groups
            "input": {},
            "given_config": {},
            "expected_sgs": None,
        },
        {  # extract single security group
            "input": {"SecurityGroups": "foo"},
            "given_config": {},
            "expected_sgs": ["foo"],
        },
        {  # extract multiple security groups
            "input": {"SecurityGroups": ["foo", "bar"]},
            "given_config": {},
            "expected_sgs": ["foo", "bar"],
        },
        {  # leave securityGroupsIds untouched
            "input": {"SecurityGroups": ["foo", "bar"]},
            "given_config": {"compute": {"launchSpecification": {"securityGroupIds": "fake-sg"}}},
            "expected_sgs": "fake-sg",
        },
    ]
    with monkeypatch.context() as m:
        for test_case in test_cases:
            mock_args = MagicMock()
            mock_args.region = "reg1"
            mock_sg = MagicMock()
            mock_sg.return_value = test_case["input"].get("SecurityGroups", None)

            def mock_resolve_security_group(sg, region):
                return sg

            m.setattr('senza.aws.resolve_security_group', mock_resolve_security_group)

            got = test_case["given_config"]
            extract_security_group_ids(test_case["input"], got, mock_args)
            assert test_case["expected_sgs"] == got["compute"]["launchSpecification"].get("securityGroupIds")


def test_missing_instance_type():
    with pytest.raises(click.UsageError):
        extract_instance_types({}, {})
    with pytest.raises(click.UsageError):
        extract_instance_types({"SpotAlternatives": ["foo", "bar", "baz"]}, {})


def test_extract_instance_types():
    test_cases = [
        {  # minimum accepted behavior, on demand instance type from typical Senza
            "input": {"InstanceType": "foo"},
            "given_config": {},
            "expected_config": {"compute": {"instanceTypes": {"ondemand": "foo", "spot": ["foo"]}}},
        },
        {  # both on demand instance type from typical Senza and spot alternatives specified
            "input": {"InstanceType": "foo", "SpotAlternatives": ["bar", "baz"]},
            "given_config": {},
            "expected_config": {"compute": {"instanceTypes": {"ondemand": "foo", "spot": ["bar", "baz"]}}},
        },
    ]
    for test_case in test_cases:
        got = test_case["given_config"]
        extract_instance_types(test_case["input"], got)
        assert test_case["expected_config"] == got


def test_extract_instance_profile(monkeypatch):
    test_cases = [
        {  # no roles specified
            "input": {},
            "given_config": {},
            "expected_config": {"compute": {"launchSpecification": {}}},
        },
        {  # leave Elastigroup iamRoles untouched
            "input": {"IamRoles": "foo", "IamInstanceProfile": "bar"},
            "given_config": {"compute": {"launchSpecification": {"iamRole": "fake-role"}}},
            "expected_config": {"compute": {"launchSpecification": {"iamRole": "fake-role"}}},
        },
        {  # convert Senza IAMRoles to iamRole
            "input": {"IamRoles": "foo"},
            "given_config": {},
            "expected_config": {"compute": {
                "launchSpecification": {"iamRole": {"name": {"Ref": "foo"}}}}},
        },
        {  # convert Senza IamInstanceProfile name to iamRole
            "input": {"IamInstanceProfile": "foo"},
            "given_config": {},
            "expected_config": {"compute": {
                "launchSpecification": {"iamRole": {"name": "foo"}}}},
        },
        {  # convert Senza IamInstanceProfile ARN to iamRole
            "input": {"IamInstanceProfile": "arn:aws:iam::12345667:instance-profile/foo"},
            "given_config": {},
            "expected_config": {"compute": {
                "launchSpecification": {"iamRole": {"arn": "arn:aws:iam::12345667:instance-profile/foo"}}}},
        },
    ]
    with monkeypatch.context() as m:
        for test_case in test_cases:
            mock_handle_iam_roles = MagicMock()
            mock_handle_iam_roles.return_value = test_case["input"].get("IamRoles")
            m.setattr("senza.components.auto_scaling_group.handle_iam_roles", mock_handle_iam_roles)
            got = test_case["given_config"]
            extract_instance_profile(MagicMock(), MagicMock(), test_case["input"], got)
            assert test_case["expected_config"] == got
