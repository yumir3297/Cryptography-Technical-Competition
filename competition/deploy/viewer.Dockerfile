# The display is the one service with a build step: the page is a Node build, and
# the process that serves it is Python.  So this image is two stages -- Node builds
# the page, then the same base the rest of the deployment runs on carries the built
# assets and the gateway.  None of it is protocol code.
#
# The Node stage is pinned to an LTS line; the page's own toolchain is pinned in
# competition/display/package.json and package-lock.json.
FROM node:24-slim AS page
WORKDIR /page
COPY competition/display/package.json competition/display/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY competition/display/ ./
RUN npm run build

FROM python:3.13-slim

ARG UID=1000
RUN useradd --uid "$UID" --create-home --shell /usr/sbin/nologin zjj

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY competition ./competition
COPY system_dev ./system_dev
COPY --from=page /page/dist ./competition/display/dist

# The caller volume is mounted here, and the gateway writes its own observer key
# into it the same way every other caller does.
RUN mkdir -p /callers && chown -R zjj:zjj /callers /app

ENV PYTHONPATH=/app \
    PYTHONUNBUFFERED=1
USER zjj

CMD ["python", "-m", "competition.deploy.viewer"]
