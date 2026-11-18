FROM python@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c
COPY wheels/ /wheels/
COPY requirements.lock /requirements.lock
RUN python -m pip install --no-cache-dir --no-index --only-binary=:all: \
    --find-links=/wheels --require-hashes -r /requirements.lock \
    && python -m pip check && rm -rf /wheels
ENV PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
USER 65532:65532
WORKDIR /workspace
