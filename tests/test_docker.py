from unittest.mock import MagicMock

import requests

from senza.docker import docker_image_exists


def test_docker_image_exists(monkeypatch):
    get = MagicMock()
    monkeypatch.setattr('requests.get', get)

    get.return_value = MagicMock(name='response')
    get.return_value.json = lambda: {'tags': ['1.0']}
    assert docker_image_exists('my-registry/foo/bar:1.0') is True

    get.side_effect = requests.HTTPError()
    assert docker_image_exists('foo/bar:1.0') is False

    get.side_effect = requests.HTTPError()
    assert docker_image_exists('my-registry/foo/bar:1.0') is False
