# Hack to upload version to Pypi

FROM registry.opensource.zalan.do/stups/python AS builder
ARG VERSION
RUN apt-get update && \
    apt-get install -q -y python3-pip && \
    pip3 install -U tox setuptools
COPY . /build
WORKDIR /build
RUN sed -i "s/__version__ = .*/__version__ = '${VERSION}'/" */__init__.py
RUN python3 setup.py sdist bdist_wheel

FROM pierone.stups.zalan.do/teapot/python-cdp-release:latest
COPY --from=builder /build/dist /pydist
