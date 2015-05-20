import requests


def docker_image_exists(docker_image: str) -> bool:
    """
    Check whether the docker image exists by calling the Docker registry REST API
    """

    parts = docker_image.split('/')
    registry = parts[0]
    repo = '/'.join(parts[1:])
    repo, tag = repo.split(':')

    for scheme in 'https', 'http':
        try:
            url = '{scheme}://{registry}/v1/repositories/{repo}/tags'.format(scheme=scheme,
                                                                             registry=registry,
                                                                             repo=repo)
            r = requests.get(url, timeout=5)
            result = r.json()
            return tag in result
        except:
            pass
    return False
