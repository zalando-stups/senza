from mock import MagicMock, mock_open

import pytest
import senza.configuration


@pytest.fixture()
def mock_path(monkeypatch):
    mock = MagicMock()
    mock.return_value = mock
    mock.__truediv__.return_value = mock

    mock.open = mock_open(read_data='{"section": {"key": "value"}}')

    monkeypatch.setattr('senza.configuration.Path', mock)
    return mock


def test_dict(mock_path: MagicMock):
    config = senza.configuration.Configuration()
    assert config.dict == {'section': {'key': 'value'}}
    assert len(config) == 1
    assert next(iter(config)) == 'section'


def test_dict_file_not_found(mock_path: MagicMock):
    mock_path.open.side_effect = FileNotFoundError
    config = senza.configuration.Configuration()
    assert config.dict == {}
    assert len(config) == 0


def test_get(mock_path: MagicMock):
    config = senza.configuration.Configuration()
    assert config['section.key'] == 'value'


def test_set(mock_path: MagicMock):
    config = senza.configuration.Configuration()
    config['section.new_key'] = 'other_value'
    mock_path.open.assert_called_with('w+')

    # new sections don't raise errors
    config['section2.new_key'] = 'other_value'


def test_del(mock_path: MagicMock):
    config = senza.configuration.Configuration()
    del config['section.key']
    mock_path.open.assert_called_with('w+')

    with pytest.raises(KeyError):
        del config['section2.new_key']
