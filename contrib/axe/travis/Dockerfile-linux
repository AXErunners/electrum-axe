FROM debian:stretch-slim
LABEL maintainer "AXErunners"

RUN apt-get update -y \
    && apt-get install -y python3-pip pyqt5-dev-tools \
        gettext python3-pycurl python3-requests git \
    && rm -rf /var/lib/apt/lists/*
