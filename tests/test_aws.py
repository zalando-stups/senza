from mock import MagicMock
from senza.aws import resolve_topic_arn


def test_create(monkeypatch):
    sns = MagicMock()
    topic = {'TopicArn': 'arn:123:mytopic'}
    sns.get_all_topics.return_value = {'ListTopicsResponse': {'ListTopicsResult': {'Topics': [topic]}}}
    monkeypatch.setattr('boto.sns.connect_to_region', MagicMock(return_value=sns))

    assert 'arn:123:mytopic' == resolve_topic_arn('myregion', 'mytopic')
