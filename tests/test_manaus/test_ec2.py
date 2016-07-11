from unittest.mock import MagicMock

import pytest
from senza.manaus.ec2 import EC2, EC2VPC
from senza.manaus.exceptions import VPCError


def test_from_boto_vpc():
    mock_vpc = MagicMock()
    mock_vpc.vpc_id = 'vpc-id'
    mock_vpc.is_default = True
    mock_vpc.tags = [{'Key': 'mykey', 'Value': 'myvalue'},
                     {'Key': 'theanswer', 'Value': '42'},
                     {'Key': 'Name', 'Value': 'my-vpc'}]
    vpc = EC2VPC.from_boto_vpc(mock_vpc)

    assert vpc.vpc_id == 'vpc-id'
    assert vpc.is_default
    assert vpc.tags['mykey'] == 'myvalue'
    assert vpc.tags['theanswer'] == '42'
    assert vpc.name == 'my-vpc'


def test_get_default_vpc(monkeypatch):
    mock_vpc1 = MagicMock()
    mock_vpc1.vpc_id = 'vpc-id1'
    mock_vpc1.is_default = True
    mock_vpc1.tags = []

    mock_vpc2 = MagicMock()
    mock_vpc2.vpc_id = 'vpc-id2'
    mock_vpc2.is_default = False
    mock_vpc2.tags = []

    mock_vpc3 = MagicMock()
    mock_vpc3.vpc_id = 'vpc-id3'
    mock_vpc3.is_default = False
    mock_vpc3.tags = []

    m_resource = MagicMock()
    m_resource.return_value = m_resource
    monkeypatch.setattr('boto3.resource', m_resource)

    ec2 = EC2('eu-test-1')

    # return default vpc
    m_resource.vpcs.all.return_value = [mock_vpc1, mock_vpc2]
    vpc1 = ec2.get_default_vpc()
    assert vpc1.vpc_id == 'vpc-id1'

    # ony one, non default
    m_resource.vpcs.all.return_value = [mock_vpc2]
    vpc2 = ec2.get_default_vpc()
    assert vpc2.vpc_id == 'vpc-id2'

    # no vpcs
    m_resource.vpcs.all.return_value = []
    with pytest.raises(VPCError) as exc_info:
        ec2.get_default_vpc()
    assert str(exc_info.value) == "Can't find any VPC!"

    # no vpcs
    m_resource.vpcs.all.return_value = [mock_vpc2, mock_vpc3]
    with pytest.raises(VPCError) as exc_info:
        ec2.get_default_vpc()

    assert str(exc_info.value) == ("Multiple VPCs are only supported if one "
                                   "VPC is the default VPC (IsDefault=true)!")


def test_get_all_vpc(monkeypatch):
    mock_vpc1 = MagicMock()
    mock_vpc1.vpc_id = 'vpc-id1'
    mock_vpc1.is_default = True
    mock_vpc1.tags = []

    mock_vpc2 = MagicMock()
    mock_vpc2.vpc_id = 'vpc-id2'
    mock_vpc2.is_default = False
    mock_vpc2.tags = []

    mock_vpc3 = MagicMock()
    mock_vpc3.vpc_id = 'vpc-id3'
    mock_vpc3.is_default = False
    mock_vpc3.tags = []

    m_resource = MagicMock()
    m_resource.return_value = m_resource
    monkeypatch.setattr('boto3.resource', m_resource)

    ec2 = EC2('eu-test-1')

    m_resource.vpcs.all.return_value = [mock_vpc1, mock_vpc2, mock_vpc3]
    vpcs = list(ec2.get_all_vpcs())
    assert len(vpcs) == 3
