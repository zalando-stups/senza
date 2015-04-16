#!/bin/sh

if [ $# -ne 1 ]; then
    >&2 echo "usage: $0 <version>"
    exit 1
fi

set -xe

python3 --version
git --version

version=$1

sed -i "s/__version__ = .*/__version__ = '${version}'/" senza/__init__.py
git add senza/__init__.py

git commit -m "Bumped version to $version"
git push

python3 setup.py clean
python3 setup.py test

python3 setup.py sdist upload

git tag ${version}
git push --tags
