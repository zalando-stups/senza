import copy

from unittest.mock import MagicMock

from senza.components.auto_scaling_group import component_auto_scaling_group


def test_component_auto_scaling_group_configurable_properties():
    definition = {"Resources": {}}
    configuration = {
        'Name': 'Foo',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'MetricsCollection': {'Granularity': '1Minute'},
        'AutoScaling': {
            'Minimum': 2,
            'Maximum': 10,
            'SuccessRequires': '4 within 30m',
            'MetricType': 'CPU',
            'Period': 60,
            'ScaleUpThreshold': 50,
            'ScaleDownThreshold': 20,
            'EvaluationPeriods': 1,
            'Cooldown': 30,
            'Statistic': 'Maximum'
        }
    }

    args = MagicMock()
    args.region = "foo"

    info = {
        'StackName': 'FooStack',
        'StackVersion': 'FooVersion'
    }

    result = component_auto_scaling_group(
        definition, configuration, args, info, False, MagicMock())

    assert result["Resources"]["FooScaleUp"] is not None
    assert result["Resources"]["FooScaleUp"]["Properties"] is not None
    assert result["Resources"]["FooScaleUp"][
        "Properties"]["ScalingAdjustment"] == "1"
    assert result["Resources"]["FooScaleUp"]["Properties"]["Cooldown"] == "30"

    assert result["Resources"]["FooScaleDown"] is not None
    assert result["Resources"]["FooScaleDown"]["Properties"] is not None
    assert result["Resources"]["FooScaleDown"][
        "Properties"]["Cooldown"] == "30"
    assert result["Resources"]["FooScaleDown"][
        "Properties"]["ScalingAdjustment"] == "-1"

    assert result["Resources"]["Foo"] is not None

    assert result["Resources"]["Foo"]["CreationPolicy"] is not None
    assert result["Resources"]["Foo"][
        "CreationPolicy"]["ResourceSignal"] is not None
    assert result["Resources"]["Foo"]["CreationPolicy"][
        "ResourceSignal"]["Timeout"] == "PT30M"
    assert result["Resources"]["Foo"]["CreationPolicy"][
        "ResourceSignal"]["Count"] == "4"

    assert result["Resources"]["Foo"]["Properties"] is not None
    assert result["Resources"]["Foo"]["Properties"]["HealthCheckType"] == "EC2"
    assert result["Resources"]["Foo"]["Properties"]["MinSize"] == 2
    assert result["Resources"]["Foo"]["Properties"]["DesiredCapacity"] == 2
    assert result["Resources"]["Foo"]["Properties"]["MaxSize"] == 10
    assert result['Resources']['Foo']['Properties'][
        'MetricsCollection'] == {'Granularity': '1Minute'}

    expected_desc = "Scale-down if CPU < 20% for 1.0 minutes (Maximum)"
    assert result["Resources"]["FooCPUAlarmHigh"][
        "Properties"]["Statistic"] == "Maximum"
    assert result["Resources"]["FooCPUAlarmLow"][
        "Properties"]["Period"] == "60"
    assert result["Resources"]["FooCPUAlarmHigh"][
        "Properties"]["EvaluationPeriods"] == "1"
    assert result["Resources"]["FooCPUAlarmLow"][
        "Properties"]["AlarmDescription"] == expected_desc


def test_component_auto_scaling_group_custom_tags():
    definition = {"Resources": {}}
    configuration = {
        'Name': 'Foo',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'Tags': [
            {'Key': 'Tag1', 'Value': 'alpha'},
            {'Key': 'Tag2', 'Value': 'beta'}
        ]
    }

    args = MagicMock()
    args.region = "foo"

    info = {
        'StackName': 'FooStack',
        'StackVersion': 'FooVersion'
    }

    result = component_auto_scaling_group(
        definition, configuration, args, info, False, MagicMock())

    assert result["Resources"]["Foo"] is not None
    assert result["Resources"]["Foo"]["Properties"] is not None
    assert result["Resources"]["Foo"]["Properties"]["Tags"] is not None
    # verify custom tags:
    t1 = next(t for t in result["Resources"]["Foo"][
              "Properties"]["Tags"] if t["Key"] == 'Tag1')
    assert t1 is not None
    assert t1["Value"] == 'alpha'
    t2 = next(t for t in result["Resources"]["Foo"][
              "Properties"]["Tags"] if t["Key"] == 'Tag2')
    assert t2 is not None
    assert t2["Value"] == 'beta'
    # verify default tags are in place:
    ts = next(t for t in result["Resources"]["Foo"][
              "Properties"]["Tags"] if t["Key"] == 'Name')
    assert ts is not None
    assert ts["Value"] == 'FooStack-FooVersion'


def test_component_auto_scaling_group_configurable_properties2():
    definition = {"Resources": {}}
    configuration = {
        'Name': 'Foo',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'SpotPrice': 0.250
    }

    args = MagicMock()
    args.region = "foo"

    info = {
        'StackName': 'FooStack',
        'StackVersion': 'FooVersion'
    }

    result = component_auto_scaling_group(
        definition, configuration, args, info, False, MagicMock())

    assert result["Resources"]["FooConfig"]["Properties"]["SpotPrice"] == 0.250

    del configuration["SpotPrice"]

    result = component_auto_scaling_group(
        definition, configuration, args, info, False, MagicMock())

    assert "SpotPrice" not in result["Resources"]["FooConfig"]["Properties"]


def test_component_auto_scaling_group_metric_type():
    definition = {"Resources": {}}
    configuration = {
        'Name': 'Foo',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'AutoScaling': {
            'Minimum': 2,
            'Maximum': 10,
            'MetricType': 'NetworkIn',
            'Period': 60,
            'EvaluationPeriods': 10,
            'ScaleUpThreshold': '50 TB',
            'ScaleDownThreshold': '10',
            'Statistic': 'Maximum'
        }
    }

    args = MagicMock()
    args.region = "foo"

    info = {
        'StackName': 'FooStack',
        'StackVersion': 'FooVersion'
    }

    result = component_auto_scaling_group(
        definition, configuration, args, info, False, MagicMock())

    expected_high_desc = "Scale-up if NetworkIn > 50 Terabytes for 10.0 minutes (Maximum)"
    assert result["Resources"]["FooNetworkAlarmHigh"] is not None
    assert result["Resources"]["FooNetworkAlarmHigh"]["Properties"] is not None
    assert result["Resources"]["FooNetworkAlarmHigh"][
        "Properties"]["MetricName"] == "NetworkIn"
    assert result["Resources"]["FooNetworkAlarmHigh"][
        "Properties"]["Unit"] == "Terabytes"
    assert result["Resources"]["FooNetworkAlarmHigh"][
        "Properties"]["Threshold"] == "50"
    assert result["Resources"]["FooNetworkAlarmHigh"][
        "Properties"]["Statistic"] == "Maximum"
    assert result["Resources"]["FooNetworkAlarmHigh"][
        "Properties"]["Period"] == "60"
    assert result["Resources"]["FooNetworkAlarmHigh"][
        "Properties"]["EvaluationPeriods"] == "10"
    assert result["Resources"]["FooNetworkAlarmHigh"][
        "Properties"]["AlarmDescription"] == expected_high_desc

    expected_low_desc = "Scale-down if NetworkIn < 10 Bytes for 10.0 minutes (Maximum)"
    assert result["Resources"]["FooNetworkAlarmLow"]is not None
    assert result["Resources"]["FooNetworkAlarmLow"]["Properties"] is not None
    assert result["Resources"]["FooNetworkAlarmLow"][
        "Properties"]["MetricName"] == "NetworkIn"
    assert result["Resources"]["FooNetworkAlarmLow"][
        "Properties"]["Unit"] == "Bytes"
    assert result["Resources"]["FooNetworkAlarmLow"][
        "Properties"]["Threshold"] == "10"
    assert result["Resources"]["FooNetworkAlarmLow"][
        "Properties"]["Statistic"] == "Maximum"
    assert result["Resources"]["FooNetworkAlarmLow"][
        "Properties"]["Period"] == "60"
    assert result["Resources"]["FooNetworkAlarmLow"][
        "Properties"]["EvaluationPeriods"] == "10"
    assert result["Resources"]["FooNetworkAlarmLow"][
        "Properties"]["AlarmDescription"] == expected_low_desc


def test_component_auto_scaling_group_optional_metric_type():
    definition = {"Resources": {}}
    configuration = {
        'Name': 'Foo',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'AutoScaling': {
            'Minimum': 2,
            'Maximum': 10,
        }
    }

    args = MagicMock()
    args.region = "foo"

    info = {
        'StackName': 'FooStack',
        'StackVersion': 'FooVersion'
    }

    result = component_auto_scaling_group(
        definition, configuration, args, info, False, MagicMock())

    assert "FooCPUAlarmHigh" not in result["Resources"]
    assert "FooNetworkAlarmHigh" not in result["Resources"]


def test_resource_overrides_autoscaling_policy():
    definition = {
        "Resources": {
            "FooScaleUp": {
                "Properties": {
                    "AdjustmentType": "ChangeInCapacity",
                    "AutoScalingGroupName": {
                        "Ref": "Foo"
                    },
                    "Cooldown": "180",
                    "ScalingAdjustment": "2"
                },
                "Type": "AWS::AutoScaling::ScalingPolicy"
            },
        }
    }

    expected = copy.copy(definition["Resources"]["FooScaleUp"])

    configuration = {
        'Name': 'Foo',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'AutoScaling': {
            'Minimum': 2,
            'Maximum': 10,
        }
    }

    args = MagicMock()
    args.region = "foo"

    info = {
        'StackName': 'FooStack',
        'StackVersion': 'FooVersion'
    }

    result = component_auto_scaling_group(
        definition, configuration, args, info, False, MagicMock())

    assert "FooScaleUp" in result["Resources"]
    assert result["Resources"]["FooScaleUp"] == expected


def test_resource_overrides_cpu_alarm():
    definition = {
        "Resources": {
            "FooCPUAlarmLow": {
                "Properties": {
                    "AlarmActions": [
                        {
                            "Ref": "FooScaleDown"
                        }
                    ],
                    "AlarmDescription": "Scale-down if CPU < 30% for 10.0 minutes (Average)",
                    "ComparisonOperator": "LessThanThreshold",
                    "Dimensions": [
                        {
                            "Name": "AutoScalingGroupName",
                            "Value": {
                                "Ref": "Foo"
                            }
                        }
                    ],
                    "EvaluationPeriods": 10,
                    "MetricName": "CPUUtilization",
                    "Namespace": "AWS/EC2",
                    "Period": 60,
                    "Statistic": "Average",
                    "Threshold": 30
                },
                "Type": "AWS::CloudWatch::Alarm"
            },
        }
    }

    expected = copy.copy(definition["Resources"]["FooCPUAlarmLow"])

    configuration = {
        'Name': 'Foo',
        'InstanceType': 't2.micro',
        'Image': 'foo',
        'AutoScaling': {
            'Minimum': 2,
            'Maximum': 10,
            'MetricType': 'NetworkIn',
            'Period': 60,
            'EvaluationPeriods': 10,
            'ScaleUpThreshold': '50 TB',
            'ScaleDownThreshold': '10',
            'Statistic': 'Maximum'
        }
    }

    args = MagicMock()
    args.region = "foo"

    info = {
        'StackName': 'FooStack',
        'StackVersion': 'FooVersion'
    }

    result = component_auto_scaling_group(
        definition, configuration, args, info, False, MagicMock())

    assert "FooCPUAlarmLow" in result["Resources"]
    assert result["Resources"]["FooCPUAlarmLow"] == expected
