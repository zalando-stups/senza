from mock import MagicMock, mock_open

import pytest
import senza.configuration
from senza.exceptions import InvalidConfigKey


class MockConfig:

    def __init__(self):
        self.open = mock_open(read_data='{"section": {"key": "value"}}')

    @property
    def parent(self):
        return self

    def mkdir(self, *args, **kwargs):
        return True


def test_dict():
    config = senza.configuration.Configuration(MockConfig())
    assert config.raw_dict == {'section': {'key': 'value'}}
    assert len(config) == 1
    assert next(iter(config)) == 'section'


def test_dict_file_not_found():
    m_config = MockConfig()
    m_config.open.side_effect = FileNotFoundError
    config = senza.configuration.Configuration(m_config)
    assert config.raw_dict == {}
    assert len(config) == 0


def test_get():
    config = senza.configuration.Configuration(MockConfig())
    assert config['section.key'] == 'value'


def test_get_bad_key():
    config = senza.configuration.Configuration(MockConfig())
    with pytest.raises(InvalidConfigKey):
        config['key']


def test_set():
    mock = MockConfig()
    config = senza.configuration.Configuration(mock)
    config['section.new_key'] = 'other_value'
    mock.open.assert_called_with('w+')

    # new sections don't raise errors
    config['section2.new_key'] = 'other_value'


def test_del():
    mock = MockConfig()
    config = senza.configuration.Configuration(mock)
    del config['section.key']
    mock.open.assert_called_with('w+')

    with pytest.raises(KeyError):
        del config['section2.new_key']
