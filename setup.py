#!/usr/bin/env python
# -*- coding: utf-8 -*-

import sys
import os
import inspect

import setuptools
from setuptools.command.test import test as TestCommand
from setuptools import setup

if sys.version_info < (3, 4, 0):
    sys.stderr.write('FATAL: STUPS Senza needs to be run with Python 3.4+\n')
    sys.exit(1)

__location__ = os.path.join(os.getcwd(), os.path.dirname(inspect.getfile(inspect.currentframe())))


def read_version(package):
    with open(os.path.join(package, '__init__.py'), 'r') as fd:
        for line in fd:
            if line.startswith('__version__ = '):
                return line.split()[-1].strip().strip("'")


NAME = 'stups-senza'
MAIN_PACKAGE = 'senza'
VERSION = read_version(MAIN_PACKAGE)
DESCRIPTION = 'AWS Cloud Formation deployment CLI'
LICENSE = 'Apache License 2.0'
URL = 'https://github.com/zalando-stups/senza'
AUTHOR = 'Henning Jacobs'
EMAIL = 'henning.jacobs@zalando.de'
KEYWORDS = 'aws cloud formation cf elb ec2 stups immutable stacks route53 boto'

COVERAGE_XML = True
COVERAGE_HTML = False
JUNIT_XML = True

# Add here all kinds of additional classifiers as defined under
# https://pypi.python.org/pypi?%3Aaction=list_classifiers
CLASSIFIERS = [
    'Development Status :: 4 - Beta',
    'Environment :: Console',
    'Intended Audience :: Developers',
    'Intended Audience :: System Administrators',
    'License :: OSI Approved :: Apache Software License',
    'Operating System :: POSIX :: Linux',
    'Programming Language :: Python',
    'Programming Language :: Python :: 3.4',
    'Programming Language :: Python :: Implementation :: CPython',
]

CONSOLE_SCRIPTS = ['senza = senza.cli:main']


class PyTest(TestCommand):

    user_options = [('cov=', None, 'Run coverage'), ('cov-xml=', None, 'Generate junit xml report'), ('cov-html=',
                    None, 'Generate junit html report'), ('junitxml=', None, 'Generate xml of test results')]

    def initialize_options(self):
        TestCommand.initialize_options(self)
        self.cov = None
        self.cov_xml = False
        self.cov_html = False
        self.junitxml = None

    def finalize_options(self):
        TestCommand.finalize_options(self)
        if self.cov is not None:
            self.cov = ['--cov', self.cov, '--cov-report', 'term-missing']
            if self.cov_xml:
                self.cov.extend(['--cov-report', 'xml'])
            if self.cov_html:
                self.cov.extend(['--cov-report', 'html'])
        if self.junitxml is not None:
            self.junitxml = ['--junitxml', self.junitxml]

    def run_tests(self):
        try:
            import pytest
        except Exception:
            raise RuntimeError('py.test is not installed, run: pip install pytest')
        params = {'args': self.test_args}
        if self.cov:
            params['args'] += self.cov
        if self.junitxml:
            params['args'] += self.junitxml
        errno = pytest.main(**params)
        sys.exit(errno)


def get_install_requirements(path):
    content = open(os.path.join(__location__, path)).read()
    return [req for req in content.split('\\n') if req != '']


def read(fname):
    return open(os.path.join(__location__, fname)).read()


def setup_package():
    # Assemble additional setup commands
    cmdclass = {}
    cmdclass['test'] = PyTest

    install_reqs = get_install_requirements('requirements.txt')

    command_options = {'test': {'test_suite': ('setup.py', 'tests'), 'cov': ('setup.py', MAIN_PACKAGE)}}
    if JUNIT_XML:
        command_options['test']['junitxml'] = 'setup.py', 'junit.xml'
    if COVERAGE_XML:
        command_options['test']['cov_xml'] = 'setup.py', True
    if COVERAGE_HTML:
        command_options['test']['cov_html'] = 'setup.py', True

    setup(
        name=NAME,
        version=VERSION,
        url=URL,
        description=DESCRIPTION,
        author=AUTHOR,
        author_email=EMAIL,
        license=LICENSE,
        keywords=KEYWORDS,
        long_description=read('README.rst'),
        classifiers=CLASSIFIERS,
        test_suite='tests',
        packages=setuptools.find_packages(exclude=['tests', 'tests.*']),
        install_requires=install_reqs,
        setup_requires=['flake8'],
        cmdclass=cmdclass,
        tests_require=['pytest-cov', 'pytest>=3.6.3', 'mock', 'responses'],
        command_options=command_options,
        entry_points={'console_scripts': CONSOLE_SCRIPTS,
                      'senza.templates': ['bgapp = senza.templates.bgapp',
                                          'postgresapp = senza.templates.postgresapp',
                                          'rediscluster = senza.templates.rediscluster',
                                          'redisnode = senza.templates.redisnode',
                                          'webapp = senza.templates.webapp']},
    )


if __name__ == '__main__':
    setup_package()
