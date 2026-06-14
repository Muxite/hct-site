# syntax=docker/dockerfile:1
#
# hct-manager — one-shot publication generator. Pure-python, fast build.
#   docker build -t hct-manager:latest .
#
# Runs to completion and exits. Writes site data to Supabase (SB_* in .env);
# data/ is mounted in (sources, templates, inputs, state). The website is a
# separate React + Vite app (../frontend) and is not part of this image.
#
# The obscura headless-browser binary is copied in from the ujin-full image so
# `run` can render Google Scholar profiles to text (build ujin:full first, via
# `docker compose --profile render build ujin-render`). obscura only needs glibc
# (libc/libm/libgcc), all present in python:3.12-slim (Debian).

FROM ujin:full AS obscura

FROM python:3.12-slim
WORKDIR /app

COPY --from=obscura /usr/local/bin/obscura /usr/local/bin/obscura

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Defaults assume the compose layout (data/ mounted in). Site data is written
# to Supabase (SB_* in .env). HCT_INDEX_HTML is unset by default — the legacy QA
# cross-check against a rendered static page only runs if you point it at one.
ENV HCT_DATA_DIR=/app/data \
    UJIN_URL=http://ujin:8901

ENTRYPOINT ["hct-manager"]
CMD ["run"]
