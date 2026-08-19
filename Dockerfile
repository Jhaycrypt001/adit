# adit-api -- the hosted HTTP surface (see src/adit/api.py's module docstring
# for the trust boundary this container is expected to run inside).
#
# Two OS-level dependencies beyond Python itself, and both are load-bearing,
# not conveniences: src/adit/remote.py shells out to `git` (to clone a
# scanned repo) and `npm` (to install its dependencies with
# --ignore-scripts) via subprocess.run with an argument list. A plain
# python:3.12-slim base has neither -- confirmed by the Windows-vs-Linux
# `npm` resolution bug already hit once in this project (see remote.py's
# `_resolve()` docstring); the fix there was PATH resolution, but the
# binary still has to exist in the image in the first place.
#
# Node comes from the official node:20-slim image via multi-stage COPY,
# not `apt-get install nodejs npm` -- Debian splits npm's own dependency
# tree into ~450 separate node-* apt packages (confirmed directly: a first
# build attempt sat downloading 143MB across those packages and was still
# not finished after 6+ minutes). Copying the prebuilt binaries out of an
# image that already did this properly is both faster and smaller.
FROM node:20-slim AS node_runtime

FROM python:3.12-slim

# git: `git clone --depth 1` in remote.cloned_repo().
# build-essential: tree-sitter-javascript/tree-sitter-typescript ship native
#   extensions; most platforms have prebuilt wheels on PyPI, but this keeps
#   the image buildable even if pip falls back to building from source for
#   this base image's exact platform tag.
RUN apt-get update && apt-get install -y --no-install-recommends \
        git \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=node_runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node_runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

WORKDIR /app

# pyproject.toml declares `readme = "README.md"` -- hatchling's metadata
# build fails outright without the file actually present (confirmed: a
# COPY of only pyproject.toml + src/ errored with "Readme file does not
# exist: README.md" before any dependency even started resolving).
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# scan_repo() clones into a fresh tempdir per request (remote.cloned_repo)
# and always removes it afterward -- no named volume needed for that churn,
# but a dedicated unprivileged user still shouldn't run as root for code
# that clones and inspects arbitrary public repositories.
RUN useradd --create-home --uid 10001 adit
USER adit

# ADIT_BOLT_URI must be overridden in docker-compose.yml to point at the
# `hydradb` service by name (bolt://hydradb:7687) -- this default only
# matches a HydraDB reachable on the container's own loopback, which is
# never true when this image runs as a separate compose service.
ENV ADIT_BOLT_URI=bolt://127.0.0.1:7687

EXPOSE 8420

CMD ["adit-api"]
