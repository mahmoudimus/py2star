FROM python:3.8-slim as builder
MAINTAINER mahmoud <@> linux.com

# Always set a working directory
WORKDIR /opt
# Sets utf-8 encoding for Python et al
ENV LANG=C.UTF-8
# Turns off writing .pyc files; superfluous on an ephemeral container.
ENV PYTHONDONTWRITEBYTECODE=1
# Seems to speed things up
ENV PYTHONUNBUFFERED=1

# Ensures that the python and pip executables used
# in the image will be those from our virtualenv.
#ENV PATH="/opt/app/venv/bin:$PATH"
ENV PYTHON_SYSTEM_PATH="/usr/lib/python3.*"
ENV PYTHON_LOCAL_PATH="/usr/local/lib/python3.*"
USER root

# App Specific
ENV PACKAGES="\
    build-essential \
    make \
    gcc \
    locales \
    file \
    python3-dev \
    "

RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
            bash \
            ca-certificates \
            ${PACKAGES} \
    && $(which python3) -m venv /opt/venv  \
    && /opt/venv/bin/python3 -m pip install --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir \
       cython \
    && apt-get remove -y --allow-remove-essential --purge ${PACKAGES} \
    && apt-get autoremove -y --allow-remove-essential \
    && apt-get clean \
    && find ${PYTHON_LOCAL_PATH} -name 'tests' -exec rm -r '{}' + \
    && find ${PYTHON_LOCAL_PATH}/site-packages/ -name '*.so' \
           -print \
           -exec sh -c 'file "{}" | grep -q "not stripped" && strip -s "{}"' \; \
    && rm -rf /root/.cache/pip \
            /tmp/* \
    && rm -rf /var/lib/apt/lists/*

FROM python:3.8-slim
MAINTAINER mahmoud <@> linux.com
WORKDIR /opt

ENV VIRTUALENV_PATH "/opt/venv"

COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /usr/local/lib /usr/local/lib
COPY --from=builder /usr/local/include /usr/local/include
COPY --from=builder ${VIRTUALENV_PATH} ${VIRTUALENV_PATH}

ADD  . /opt/app
VOLUME /opt/app

# make some useful symlinks that are expected to exist
RUN apt-get update \
   && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
                bash \
                ca-certificates \
                libreadline7 \
    && ldconfig \
    && cd /usr/local/bin \
    && rm idle pydoc python python-config \
    && ln -Fs idle3 idle \
    && ln -Fs pydoc3 pydoc \
    && ln -Fs python3 python \
    && ln -Fs python3-config python-config \
    && cd /opt/app \
    && ${VIRTUALENV_PATH}/bin/pip install --no-cache-dir -e .[tests]  \
    && rm -rf /root/.cache/pip \
                /tmp/* \
    && rm -rf /var/lib/apt/lists/*

CMD ["/bin/bash"]
