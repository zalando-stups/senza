import click
import requests
import time
import json
from pathlib import Path
from senza.components.subnet_auto_configuration import component_subnet_auto_configuration
from senza.aws import resolve_security_groups
from senza.utils import ensure_keys

'''
Multiple Subnets are possible, but only with private IPs:
http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-fleet-examples.html#fleet-config2
With public ips are networkInterfaces block for every type and subnet nescessary

algorithm for WeightedCapacity
http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-fleet-examples.html#fleet-config6
http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-fleet.html#spot-instance-weighting

Tags are not supported
http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-requests.html#concepts-spot-instances-request-tags

AllocationStrategy
http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/spot-fleet.html#spot-fleet-allocation-strategy
'''


SPOT_ADVISOR_URL = 'https://spot-bid-advisor.s3.amazonaws.com/spot-advisor.json'
EC2_PRICE_URL = 'https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/index.json'
ONE_DAY = 86400  # seconds


def load_prices_and_spot_advisor():
    prices = load_from_disk()
    update_cache(prices)
    return prices


def load_from_disk():
    spotfleet_cache = Path(click.get_app_dir('senza')) / 'spotfleet.json'
    now = time.time()
    if (spotfleet_cache.exists() and
            now - spotfleet_cache.stat().st_mtime < ONE_DAY):
        with spotfleet_cache.open() as spotfleet_cache_file:
            try:
                return json.load(spotfleet_cache_file)
            except:
                return {}
    return {}


def update_cache(price_cache: dict):
    regionMap = {
        'AWS GovCloud (US)': 'us-gov-west-1',
        'US East (N. Virginia)': 'us-east-1',
        'US East (Ohio)': 'us-east-2',
        'US West (N. California)': 'us-west-1',
        'US West (Oregon)': 'us-west-2',
        'Asia Pacific (Mumbai)': 'ap-south-1',
        'Asia Pacific (Seoul)': 'ap-northeast-2',
        'Asia Pacific (Singapore)': 'ap-southeast-1',
        'Asia Pacific (Sydney)': 'ap-southeast-2',
        'Asia Pacific (Tokyo)': 'ap-northeast-1',
        'EU (Frankfurt)': 'eu-central-1',
        'EU (London)': 'eu-west-2',
        'EU (Ireland)': 'eu-west-1',
        'South America (Sao Paulo)': 'sa-east-1',
        'Canada (Central)': 'ca-central-1'}
    cache_updated = False
    request_headers = {}
    if price_cache.get('EC2_PRICE_LAST_MODIFIED'):
        request_headers['If-Modified-Since'] = price_cache.get('EC2_PRICE_LAST_MODIFIED')
    response = requests.get(EC2_PRICE_URL, timeout=5, headers=request_headers)
    response.raise_for_status()
    if response.status_code == 200:
        price_cache['EC2_PRICE_LAST_MODIFIED'] = response.headers['Last-Modified']
        prices = response.json()

        pricelist = {}
        for value in prices['products'].values():
            if (value['attributes']['servicecode'] == 'AmazonEC2'
                    and value['attributes'].get('operatingSystem') == 'Linux'
                    and value['attributes'].get('tenancy') == 'Shared'):
                region = regionMap.get(value['attributes']['location'],
                                       'Unknown region: {}'.format(value['attributes']['location']))
                value['attributes']['productFamily'] = value['productFamily']
                value['attributes']['sku'] = value['sku']
                value['attributes']['price'] = float(prices['terms']['OnDemand'][value['sku']]['{}.JRTCKXETXF'.format(
                    value['sku'])]['priceDimensions']['{}.JRTCKXETXF.6YS6EN2CT7'.format(
                        value['sku'])]['pricePerUnit']['USD'])

                if region not in pricelist:
                    pricelist[region] = {}
                pricelist[region][value['attributes']['instanceType']] = value['attributes']
        cache_updated = True
        price_cache['prices'] = pricelist
    request_headers = {}
    if price_cache.get('SPOT_ADVISOR_LAST_MODIFIED'):
        request_headers['If-Modified-Since'] = price_cache.get('SPOT_ADVISOR_LAST_MODIFIED')
    response = requests.get(SPOT_ADVISOR_URL, timeout=5, headers=request_headers)
    response.raise_for_status()
    if response.status_code == 200:
        price_cache['SPOT_ADVISOR_LAST_MODIFIED'] = response.headers['Last-Modified']
        cache_updated = True
        price_cache['spot_advisor'] = response.json()
    if cache_updated:
        spotfleet_cache = Path(click.get_app_dir('senza')) / 'spotfleet.json'
        try:
            spotfleet_cache.parent.mkdir(parents=True)
        except FileExistsError:
            # this try...except can be replaced with exist_ok=True when
            # we drop python3.4 support
            pass
        with spotfleet_cache.open('w') as spotfleet_cache_file:
            json.dump(price_cache, spotfleet_cache_file, indent=2, sort_keys=True)


def component_spot_fleet_auto_configuration(definition, configuration, args, info, force, account_info):
    definition = ensure_keys(definition, "Resources")
    component_subnet_auto_configuration(definition, configuration, args, info, force, account_info)

    # launch configuration
    config_name = configuration["Name"] + "Config"
    launch_specification, max_price = get_launch_specifications(configuration, account_info)
    definition["Resources"][config_name] = {
        "Type": "AWS::EC2::SpotFleet",
        "Properties": {
            "SpotFleetRequestConfigData": {
                "IamFleetRole": "arn:aws:iam::{}:role/EC2SpotFleet".format(account_info.AccountID),
                "LaunchSpecifications": launch_specification,
                "SpotPrice": max_price,
                "TargetCapacity": configuration["TargetCapacity"]
            }
        }
    }

    if "AllocationStrategy" in configuration:
        definition["Resources"][config_name]["Properties"]["SpotFleetRequestConfigData"]["AllocationStrategy"] = \
            configuration["AllocationStrategy"]

    return definition


def select_instance_types(configuration, prices):
    if configuration.get('instance_types'):
        if isinstance(configuration['instance_types'], str):
            return configuration['instance_types'].split(',')
        elif isinstance(configuration['instance_types'], list):
            return configuration['instance_types']

    min_cpu = configuration.get('min_cpu', 0)
    min_ram = configuration.get('min_ram', 0)
    instances = []
    for instance_type, instance_data in prices['spot_advisor']['instance_types'].items():
        if min_cpu <= instance_data['cores'] and min_ram <= instance_data['ram_gb']:
            instances.append(instance_type)
    return instances


def get_instance_parameters(configuration, account_info):
    prices = load_prices_and_spot_advisor()
    instance_types = []
    for instance_type in select_instance_types(configuration, prices):
        if instance_type in prices['prices'][account_info.Region]:
            instance_types.append(prices['prices'][account_info.Region][instance_type])

    instance_types.sort(key=lambda x: (x['price'], x['instanceType']))

    return instance_types


def get_launch_specifications(configuration, account_info):
    launch_specifications = []
    subnetlist = []
    max_price = 0.0
    if configuration.get("AssociatePublicIpAddress", False):
        subnetlist = configuration["ServerSubnets"][account_info.Region]
    else:
        subnetlist = [','.join(configuration["ServerSubnets"][account_info.Region])]

    for instance_type in get_instance_parameters(configuration, account_info):
        if instance_type["price"] > max_price:
            max_price = instance_type["price"]
        for subnet in subnetlist:
            launch_specification = {
                "ImageId": {"Fn::FindInMap": ["Images", {"Ref": "AWS::Region"}, configuration["Image"]]},
                "InstanceType": instance_type["instanceType"],
                "SpotPrice": instance_type["price"],
                "EbsOptimized": configuration.get('EbsOptimized', False)
            }

        if 'BlockDeviceMappings' in configuration:
            launch_specification['BlockDeviceMappings'] = configuration['BlockDeviceMappings']

        if "IamInstanceProfile" in configuration:
            launch_specification["IamInstanceProfile"] = configuration["IamInstanceProfile"]

        if "UserData" in configuration:
            launch_specification["UserData"] = configuration["UserData"]

        if configuration.get("AssociatePublicIpAddress", False):
            launch_specification["NetworkInterfaces"] = [
                {
                    "AssociatePublicIpAddress": True,
                    "DeleteOnTermination": True,
                    "DeviceIndex": 0,
                    "Groups": [
                        {
                            "Ref": "WorkerSecurityGroup"
                        }
                    ],
                    "SubnetId": subnet
                }
            ]
            if "SecurityGroups" in configuration:
                launch_specification["NetworkInterfaces"][0]["Groups"] = \
                    resolve_security_groups(configuration["SecurityGroups"], account_info.Region)
        else:
            launch_specification["SubnetId"] = subnet
            if "SecurityGroups" in configuration:
                launch_specification["SecurityGroups"] = \
                    resolve_security_groups(configuration["SecurityGroups"], account_info.Region)
        launch_specifications.append(launch_specification)

    return launch_specifications, max_price
