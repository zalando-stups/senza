import boto3
import io
from clickclick import Action
from senza.definitions import AccountArguments
from ..templates._helper import check_s3_bucket


def save_template_in_s3(data: dict, region: str):
    account_info = AccountArguments(region=region)
    bucket_name = 'senza-deploy-{}-{}'.format(account_info.AccountID, account_info.AccountAlias)
    obj_name = '{}/{}'.format(region, data['StackName'])
    check_s3_bucket(bucket_name, region)
    s3 = boto3.resource('s3')
    bucket = s3.Bucket(bucket_name)
    obj = bucket.Object(obj_name)
    with Action("Upload Template to S3 bucket {}...".format(bucket_name)):
        obj.upload_fileobj(io.BytesIO(data['TemplateBody'].encode()))
    del(data['TemplateBody'])
    data['TemplateURL'] = 'https://s3.amazonaws.com/{}/{}'.format(bucket_name, obj_name)
