import re
from pathlib import Path

import yaml
from click import FileError

from .aws import StackReference

VERSION_RE = re.compile(r'v[0-9][a-zA-Z0-9-]*$')


def all_with_version(stack_refs: list):
    """
    >>> all_with_version([StackReference(name='foobar-stack', version='1'), \
                          StackReference(name='other-stack', version=None)])
    False
    >>> all_with_version([StackReference(name='foobar-stack', version='1'), \
                          StackReference(name='other-stack', version='v23')])
    True
    >>> all_with_version([StackReference(name='foobar-stack', version='1')])
    True
    >>> all_with_version([StackReference(name='other-stack', version=None)])
    False
    """
    for ref in stack_refs:
        if not ref.version:
            return False
    return True


def get_stack_refs(refs: list):
    """
    >>> get_stack_refs(['foobar-stack'])
    [StackReference(name='foobar-stack', version=None)]

    >>> get_stack_refs(['foobar-stack', '1'])
    [StackReference(name='foobar-stack', version='1')]

    >>> get_stack_refs(['foobar-stack', '1', 'other-stack'])
    [StackReference(name='foobar-stack', version='1'), StackReference(name='other-stack', version=None)]

    >>> get_stack_refs(['foobar-stack', 'v1', 'v2', 'v99', 'other-stack'])
    [StackReference(name='foobar-stack', version='v1'), StackReference(name='foobar-stack', version='v2'), \
StackReference(name='foobar-stack', version='v99'), StackReference(name='other-stack', version=None)]
    """
    refs = list(refs)
    refs.reverse()
    stack_refs = []
    last_stack = None
    while refs:
        ref = refs.pop()
        if last_stack is not None and VERSION_RE.match(ref):
            stack_refs.append(StackReference(last_stack, ref))
        else:
            try:
                with open(ref) as fd:
                    data = yaml.safe_load(fd)
                ref = data['SenzaInfo']['StackName']
            except (OSError, IOError):
                # It's still possible that the ref is a regex
                pass

            if refs:
                version = refs.pop()
            else:
                version = None
            stack_refs.append(StackReference(ref, version))
            last_stack = ref
    return stack_refs


def get_stack_refs_from_file(file_references: list) -> list:
    # ((1.0, 2.0), (6.0, 4.0))
    stack_references = []
    for reference in file_references:
        path, version = reference
        try:
            with Path(path).open() as fd:
                data = yaml.safe_load(fd)
        except (OSError, IOError) as error:
            raise FileError(path, str(error))
        name = data['SenzaInfo']['StackName']
        version = version if version != '-' else None
        stack_references.append(StackReference(name, version))
    return stack_references
