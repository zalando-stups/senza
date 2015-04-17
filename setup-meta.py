#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Additional setup to register the convenience meta package on PyPI
"""

import setuptools
import setup

from setup import VERSION, DESCRIPTION, LICENSE, URL, AUTHOR, EMAIL, KEYWORDS, CLASSIFIERS


NAME = 'senza'


def setup_package():
    version = VERSION

    install_reqs = [setup.NAME]

    setuptools.setup(
        name=NAME,
        version=version,
        url=URL,
        description=DESCRIPTION,
        author=AUTHOR,
        author_email=EMAIL,
        license=LICENSE,
        keywords=KEYWORDS,
        long_description='This is just a meta package. Please use https://pypi.python.org/pypi/{}'.format(setup.NAME),
        classifiers=CLASSIFIERS,
        packages=[],
        install_requires=install_reqs,
    )


if __name__ == '__main__':
    setup_package()
