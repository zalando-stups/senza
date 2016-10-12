"""
Functions and classes related to Senza Definition files
"""

# pylint: disable=invalid-name

import sys

from clickclick import choice
from senza.aws import get_account_alias, get_account_id
from senza.manaus.ec2 import EC2
from senza.manaus.exceptions import VPCError
from senza.manaus.route53 import Route53
from senza.templates._helper import get_mint_bucket_name


class AccountArguments:
    """
    Account arguments to use in the definitions
    """
    def __init__(self, region):
        self.Region = region
        self.__AccountAlias = None
        self.__AccountID = None
        self.__Domain = None
        self.__MintBucket = None
        self.__TeamID = None
        self.__VpcID = None

    @property
    def AccountID(self) -> str:
        """
        Returns the (non-human friendly) account id
        """
        if self.__AccountID is None:
            self.__AccountID = get_account_id()
        return self.__AccountID

    @property
    def AccountAlias(self) -> str:
        """
        Returns the human readable account alias
        """
        if self.__AccountAlias is None:
            self.__AccountAlias = get_account_alias()
        return self.__AccountAlias

    @property
    def Domain(self) -> str:
        """
        Return the domain name for the account.
        """
        if self.__Domain is None:
            self.__setDomain()
        return self.__Domain.rstrip('.')

    def __setDomain(self, domain_name=None) -> str:
        """
        Sets domain for account. If there's only one hosted zone matching the
        domain_name it will be  used otherwise the user will be presented with
        a choice.
        """
        domain_list = list(Route53.get_hosted_zones(domain_name))
        if len(domain_list) == 0:
            raise AttributeError('No Domain configured')
        elif len(domain_list) > 1:
            domain = choice('Please select the domain',
                            sorted(domain.domain_name
                                   for domain in domain_list))
        else:
            domain = domain_list[0].domain_name
        self.__Domain = domain
        return domain

    def split_domain(self, domain_name):
        """
        Splits domain_name in sub_domain and main_domain based on the account
        domain.
        """
        self.__setDomain(domain_name)
        if domain_name.endswith('.{}'.format(self.Domain)):
            return domain_name[:-len('.{}'.format(self.Domain))], self.Domain
        else:
            # default behaviour for unknown domains
            return domain_name.split('.', 1)

    @property
    def TeamID(self) -> str:
        """
        Returns the team id based on the account name
        """
        if self.__TeamID is None:
            self.__TeamID = self.AccountAlias.split('-', maxsplit=1)[-1]
        return self.__TeamID

    @property
    def VpcID(self) -> str:
        """
        Returns the VPC ID to use. If a there's a default VPC it returns that
        one, otherwise it will provide the user a choice if running in an
        interactive terminal or raise an exception otherwise.
        """
        if self.__VpcID is None:
            ec2 = EC2(self.Region)
            try:
                vpc = ec2.get_default_vpc()
            except VPCError as error:
                if sys.stdin.isatty() and error.number_of_vpcs:
                    # if running in interactive terminal and there are VPCs
                    # to choose from
                    vpcs = ec2.get_all_vpcs()
                    options = [(vpc.vpc_id, str(vpc)) for vpc in vpcs]
                    print("Can't find a default VPC")
                    vpc = choice("Select VPC to use",
                                 options=options)
                else:  # if not running in interactive terminal (e.g Jenkins)
                    raise
            self.__VpcID = vpc.vpc_id
        return self.__VpcID

    @property
    def MintBucket(self) -> str:
        """
        Returns the mintbucket for the current account
        """
        if self.__MintBucket is None:
            self.__MintBucket = get_mint_bucket_name(self.Region)
        return self.__MintBucket
