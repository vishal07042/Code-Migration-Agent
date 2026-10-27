# Sandbox image for running generated code: no network, CPU/memory limits.
# Build: docker build -t migrate-sandbox:latest sandbox/
# Run:   enforced by sandbox/run.py (docker run --network none -m 512m --cpus 1).
FROM python:3.11-slim

RUN apt-get update \
  && apt-get install -y --no-install-recommends nodejs npm \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /work
COPY sandbox/requirements-sandbox.txt /tmp/requirements-sandbox.txt
RUN pip install --no-cache-dir -r /tmp/requirements-sandbox.txt

# No ENTRYPOINT: sandbox/run.py supplies the command per run.
CMD ["python", "--version"]
