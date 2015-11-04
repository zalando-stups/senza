
from senza.aws import resolve_security_groups
from senza.utils import ensure_keys


def component_redis_cluster(definition, configuration, args, info, force, account_info):
    name = configuration["Name"]
    definition = ensure_keys(definition, "Resources")

    number_of_nodes = int(configuration.get('NumberOfNodes', '2'))

    definition["Resources"]["RedisReplicationGroup"] = {
        "Type": "AWS::ElastiCache::ReplicationGroup",
        "Properties": {
            "AutomaticFailoverEnabled": True,
            "CacheNodeType": configuration.get('CacheNodeType', 'cache.t2.small'),
            "CacheSubnetGroupName": {
                "Ref": "RedisSubnetGroup"
            },
            "Engine": "redis",
            "EngineVersion": configuration.get('EngineVersion', '2.8.19'),
            "CacheParameterGroupName": configuration.get('CacheParameterGroupName', 'default.redis2.8'),
            "NumCacheClusters": number_of_nodes,
            "SecurityGroupIds": resolve_security_groups(configuration["SecurityGroups"], args.region),
            "ReplicationGroupDescription": "Redis replicated cache cluster: " + name,
        }
    }

    definition["Resources"]["RedisSubnetGroup"] = {
        "Type": "AWS::ElastiCache::SubnetGroup",
        "Properties": {
            "Description": "Redis cluster subnet group",
            "SubnetIds": {"Fn::FindInMap": ["ServerSubnets", {"Ref": "AWS::Region"}, "Subnets"]}
        }
    }

    return definition
