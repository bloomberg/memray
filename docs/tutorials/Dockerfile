FROM debian:bookworm-slim

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --force-yes --no-install-recommends \
    python3-dev \
    python3-dbg \
    python3-pip \
    python3-venv \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV VIRTUAL_ENV=/venv \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/bin:$PATH

RUN python3 -m venv "$VIRTUAL_ENV"

ENV PATH="${VIRTUAL_ENV}/bin:/usr/lib/ccache:${PATH}" \
    PYTHON="${VIRTUAL_ENV}/bin/python"

COPY requirements-tutorial.txt /tmp/

RUN $PYTHON -m pip install -U \
    -r /tmp/requirements-tutorial.txt

WORKDIR /src
