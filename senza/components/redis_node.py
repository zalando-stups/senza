
from senza.aws import resolve_security_groups
from senza.utils import ensure_keys


def component_redis_node(definition, configuration, args, info, force, account_info):
    name = configuration["Name"]
    definition = ensure_keys(definition, "Resources")

    definition["Resources"]["RedisCacheCluster"] = {
        "Type": "AWS::ElastiCache::CacheCluster",
        "Properties": {
            "ClusterName": name,
            "Engine": "redis",
            "EngineVersion": configuration.get('EngineVersion', '2.8.19'),
            "CacheParameterGroupName": configuration.get('CacheParameterGroupName', 'default.redis2.8'),
            "NumCacheNodes": 1,
            "CacheNodeType": configuration.get('CacheNodeType', 'cache.t2.small'),
            "CacheSubnetGroupName": {
                "Ref": "RedisSubnetGroup"
            },
            "VpcSecurityGroupIds": resolve_security_groups(configuration["SecurityGroups"], args.region)
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
