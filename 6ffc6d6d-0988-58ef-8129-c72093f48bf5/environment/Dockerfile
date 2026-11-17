# The repository the agent reads, at the sole parent of the fix commit. The task is read-only:
# the image needs git and a python3 to run sanitize.py, and nothing that builds or runs the code.
FROM python:3.12-bookworm@sha256:581429e3df12d76e6af4be5ab7d0e7fc2013eb57dc23d2de691411c8efdbb970

RUN mkdir -p /logs/agent /logs/verifier /logs/artifacts /tests /solution /workspace

# Sanitize, then replace the history with one base commit. The sanitizer skips .git/, so old
# packs would hand back the stripped comments; and [[verifier.collect]] diffs against this
# base commit to detect any change the agent made to the checkout.
COPY sanitize.py /opt/hg/sanitize.py
WORKDIR /workspace/pandas-dev__pandas
RUN git init -q . \
 && git fetch -q --depth 1 https://github.com/pandas-dev/pandas.git 03e5d938adbd3ec9314c326b002170b73bde2c9f \
 && git checkout -q FETCH_HEAD \
 && python3 /opt/hg/sanitize.py /workspace/pandas-dev__pandas --languages python --strip-tests \
 && rm -rf .git \
 && git init -q -b base . \
 && git -c user.email=harbor@local -c user.name=harbor add -A \
 && git -c user.email=harbor@local -c user.name=harbor commit -q -m base
WORKDIR /workspace
RUN groupadd --gid 1000 agent \
 && useradd --uid 1000 --gid 1000 --create-home --home-dir /home/agent --shell /bin/bash agent \
 && git config --system --add safe.directory '*' \
 && chown -R 1000:1000 /workspace

# Not the checkout root: the agent's own tooling runs from the working directory.
WORKDIR /workspace
