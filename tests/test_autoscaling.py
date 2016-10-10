import copy
import click
import pytest

from unittest.mock import MagicMock

from senza.components.auto_scaling_group import component_auto_scaling_group


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
            "FooScaleDown": {
                "Properties": {
                    "AdjustmentType": "ChangeInCapacity",
                    "AutoScalingGroupName": {
                        "Ref": "Foo"
                    },
                    "Cooldown": "90",
                    "ScalingAdjustment": "-3"
                },
                "Type": "AWS::AutoScaling::ScalingPolicy"
            },
        }
    }

    expected = copy.copy(definition["Resources"])

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

    assert result["Resources"]["FooScaleUp"] == expected["FooScaleUp"]
    assert result["Resources"]["FooScaleDown"] == expected["FooScaleDown"]


def test_resource_overrides_autoscaling_policy_with_incorrect_ref():
    definition = {
        "Resources": {
            "FooScaleUp": {
                "Properties": {
                    "AdjustmentType": "ChangeInCapacity",
                    "AutoScalingGroupName": {
                        "Ref": "NotFoo"
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

    with pytest.raises(click.exceptions.UsageError):
        result = component_auto_scaling_group(
            definition, configuration, args, info, False, MagicMock())


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
