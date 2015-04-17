import re
import requests
import shlex


REGISTRY_PATTERN = re.compile("^(([a-zA-Z]|[a-zA-Z][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*" +
                              "([A-Za-z]|[A-Za-z][A-Za-z0-9\-]*[A-Za-z0-9])(\:[0-9]+)?$")
REGISTRY_IP_PATTERN = re.compile("^(([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}" +
                                 "([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])(\:[0-9]+)?$")


def generate_env_options(env_vars: dict):
    """
    Generate Docker env options (-e) for a given dictionary

    >>> generate_env_options({})
    ''

    >>> generate_env_options({'a': 1})
    '-e a=1'

    >>> generate_env_options({'a': '; rm -fr'})
    "-e 'a=; rm -fr'"
    """
    options = []
    for key, value in sorted(env_vars.items()):
        options.append('-e')
        options.append(shlex.quote('{}={}'.format(key, value)))

    return ' '.join(options)


def extract_repository_and_tag(repo_name: str):
    """
    >>> extract_repository_and_tag('foo/bar:1.0')
    ('foo/bar', '1.0')
    """
    splits = repo_name.split(':')
    if len(splits) == 2:
        return (splits[0], splits[1])
    else:
        return (repo_name, '')


def is_tag_valid(extracted: tuple) -> bool:
    """
    >>> is_tag_valid(('', ))
    False
    >>> is_tag_valid(('foo/bar', '1.0'))
    True
    """
    re_tag = re.compile('[a-zA-Z0-9-_.]+')

    if len(extracted) > 1:
        return re_tag.match(extracted[1]) is not None
    else:
        return False


def extract_registry(docker_image: str) -> str:
    """
    >>> extract_registry('nginx')

    >>> extract_registry('foo.bar.example.com:2195/namespace/my_repo:1.0')
    'foo.bar.example.com:2195'
    """

    parts = docker_image.split('/')
    if len(parts) == 3:
        return parts[0]
    return None


def replace_registry(docker_image: str, registry: str) -> str:
    """
    >>> replace_registry('myrepo/myapp', 'myreg')
    'myreg/myrepo/myapp'

    >>> replace_registry('somereg/myrepo/myapp', 'myreg')
    'myreg/myrepo/myapp'

    >>> replace_registry('myreg/myrepo/myapp', 'myreg')
    'myreg/myrepo/myapp'
    """
    parts = docker_image.split('/')
    if len(parts) >= 3:
        parts_without_registry = parts[1:]
    else:
        parts_without_registry = parts
    return '/'.join([registry] + parts_without_registry)


def is_docker_image_valid(docker_image: str) -> bool:
    """
    >>> is_docker_image_valid('nginx')
    False

    >>> is_docker_image_valid('nginx:latest')
    True

    >>> is_docker_image_valid('foo/bar:1.0')
    True

    >>> is_docker_image_valid('foo.bar.example.com:2195/namespace/my_repo:1.0')
    True
    """
    parts = docker_image.split('/')
    number_of_parts = len(parts)
    extracted = extract_repository_and_tag(parts[number_of_parts - 1])

    is_valid_tag = is_tag_valid(extracted)
    if not is_valid_tag:
        return False

    re_namespace = re.compile('[a-z0-9_]+')
    re_repo_name = re.compile('[a-zA-Z0-9-_.]+')

    extracted_repo_part = extracted[0]

    if number_of_parts == 1:
        # only repository name was specified
        return re_repo_name.match(extracted_repo_part) is not None
    elif number_of_parts == 2:
        # namspace and repository were specifed (e.g. namespace/my_repo:1.0)
        is_namespace_valid = re_namespace.match(parts[0]) is not None
        is_repo_valid = re_repo_name.match(extracted_repo_part) is not None
        return is_repo_valid and is_namespace_valid
    elif number_of_parts == 3:
        # private registry, namspace and repository were specified
        # (e.g. foo.bar.example.com:2195/namespace/my_repo:1.0)
        is_registry_valid = REGISTRY_PATTERN.match(parts[0]) is not None
        if not is_registry_valid:
            is_registry_valid = REGISTRY_IP_PATTERN.match(parts[0]) is not None

        is_namespace_valid = re_namespace.match(parts[1]) is not None
        is_repo_valid = re_repo_name.match(extracted_repo_part) is not None

        return is_registry_valid and is_namespace_valid and is_repo_valid
    else:
        return False


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
