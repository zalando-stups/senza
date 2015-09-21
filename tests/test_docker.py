from unittest.mock import MagicMock
from senza.docker import docker_image_exists


def test_docker_image_exists(monkeypatch):
    get = MagicMock()
    monkeypatch.setattr('requests.get', get)

    get.return_value = MagicMock(name='response')
    get.return_value.json = lambda: {'1.0': 'foo'}
    assert docker_image_exists('my-registry/foo/bar:1.0') is True

    get.return_value = None
    assert docker_image_exists('foo/bar:1.0') is False

    get.return_value = None
    assert docker_image_exists('my-registry/foo/bar:1.0') is False
