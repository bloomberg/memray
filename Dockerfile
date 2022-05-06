FROM debian:latest

RUN apt-get update \
    && apt-get install -y --force-yes --no-install-recommends \
    build-essential \
    libunwind-dev \
    liblz4-dev \
    pkg-config \
    python3-dev \
    python3-dbg \
    python3-pip \
    python3-venv \
    make \
    cmake \
    gdb \
    valgrind \
    lcov \
    nodejs \
    npm \
    clang-format \
    git \
    ccache \
    wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/bin:$PATH \
    CC=gcc \
    CXX=g++

RUN python3.9 -m venv "$VIRTUAL_ENV"

ENV PATH="${VIRTUAL_ENV}/bin:${PATH}" \
    PYTHON="${VIRTUAL_ENV}/bin/python"

COPY requirements-test.txt requirements-extra.txt requirements-docs.txt /tmp/

RUN $PYTHON -m pip install -U \
    -r /tmp/requirements-extra.txt \
    -r /tmp/requirements-test.txt \
    -r /tmp/requirements-docs.txt \
    cython \
    setuptools \
    wheel

RUN npm install -g prettier

RUN ln -s /usr/bin/ccache /bin/g++ \
    && ln -s /usr/bin/ccache /bin/gcc

WORKDIR /src
