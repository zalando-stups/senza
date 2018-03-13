import boto3
from collections import namedtuple

TaupageChannel = namedtuple("TaupageChannel", ("image_mapping", "ami_wildcard", "public_ami_wildcard"))


def _channel(suffix):
    return TaupageChannel("LatestTaupage{}Image".format(suffix),
                          "Taupage{}-AMI-*".format(suffix),
                          "Taupage{}-Public-AMI-*".format(suffix))


DEFAULT_CHANNEL = _channel("")

CHANNELS = {
    "latest": DEFAULT_CHANNEL,
    "staging": _channel("Staging"),
    "dev": _channel("Dev")
}


def find_image(region: str, channel: TaupageChannel = None):
    '''Find the latest Taupage AMI, first try private images, fallback to public'''

    if channel is None:
        channel = DEFAULT_CHANNEL

    ec2 = boto3.resource('ec2', region)
    filters = [{'Name': 'name', 'Values': [channel.ami_wildcard]},
               {'Name': 'is-public', 'Values': ['false']},
               {'Name': 'state', 'Values': ['available']},
               {'Name': 'root-device-type', 'Values': ['ebs']}]
    images = list(ec2.images.filter(Filters=filters))
    if not images:
        public_filters = [{'Name': 'name', 'Values': [channel.public_ami_wildcard]},
                          {'Name': 'is-public', 'Values': ['true']},
                          {'Name': 'state', 'Values': ['available']},
                          {'Name': 'root-device-type', 'Values': ['ebs']}]
        images = list(ec2.images.filter(Filters=public_filters))

    if not images:
        return None

    most_recent_image = sorted(images, key=lambda i: i.name)[-1]
    return most_recent_image
