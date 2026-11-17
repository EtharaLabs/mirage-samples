# Dedicated verifier image. Judge credentials reach only this container.
FROM python:3.12-bookworm@sha256:581429e3df12d76e6af4be5ab7d0e7fc2013eb57dc23d2de691411c8efdbb970

RUN pip install --no-cache-dir 'harbor-rewardkit==0.2.4' \
 && rewardkit --help > /dev/null

RUN mkdir -p /logs/agent /logs/verifier /logs/artifacts /tests /app /workspace

COPY . /tests/
RUN chmod +x /tests/test.sh
WORKDIR /tests
