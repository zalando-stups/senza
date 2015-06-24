import json
import click
from unittest.mock import MagicMock
from senza.components import component_load_balancer


def test_component_load_balancer_healthcheck(monkeypatch):
    configuration = {
        "Name": "test_lb",
        "SecurityGroups": "",
        "HTTPPort": "9999",
        "HealthCheckPath": "/healthcheck"
    }
    
    definition = { "Resources": {}}

    args = MagicMock()
    args.region = "foo"
    
    mock_string_result = MagicMock()
    mock_string_result.return_value = "foo"
    monkeypatch.setattr('senza.components.find_ssl_certificate_arn', mock_string_result)
    monkeypatch.setattr('senza.components.resolve_security_groups', mock_string_result)
    
    result = component_load_balancer(definition, configuration, args, MagicMock(), False)
    # Defaults to HTTP
    assert "HTTP:9999/healthcheck" == result["Resources"]["test_lb"]["Properties"]["HealthCheck"]["Target"]

    # Supports other AWS protocols
    configuration["HealthCheckProtocol"] = "TCP"
    result = component_load_balancer(definition, configuration, args, MagicMock(), False)
    assert "TCP:9999/healthcheck" == result["Resources"]["test_lb"]["Properties"]["HealthCheck"]["Target"]

    # Will fail on incorrect protocol
    configuration["HealthCheckProtocol"] = "MYFANCYPROTOCOL"
    try:
        component_load_balancer(definition, configuration, args, MagicMock(), False)
    except click.UsageError:
        pass
    except:
        assert False, "check for supported protocols failed"

