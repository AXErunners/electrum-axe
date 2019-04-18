FROM ubuntu:18.04
LABEL maintainer "AXErunners"

RUN apt-get update -y \
    && apt-get install -y python3-pip \
        gettext python3-pycurl python3-requests git \
    && rm -rf /var/lib/apt/lists/*
