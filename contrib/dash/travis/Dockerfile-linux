FROM ubuntu:18.04
LABEL maintainer "Andriy Khavryuchenko <akhavr@khavr.com>"

RUN apt-get update -y \
    && apt-get install -y python3-pip \
        gettext python3-pycurl python3-requests git \
    && rm -rf /var/lib/apt/lists/*
