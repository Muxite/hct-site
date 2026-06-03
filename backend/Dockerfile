# syntax=docker/dockerfile:1
#
# hct-manager — one-shot publication generator. Pure-python, fast build.
#   docker build -t hct-manager:latest .
#
# Runs to completion and exits. Writes site data to Supabase (SB_* in .env);
# data/ + the static frontend/ are mounted in as read inputs.

FROM python:3.12-slim
WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# Defaults assume the compose layout (data + frontend mounted in). Site data
# is written to Supabase (SB_* in .env); the frontend mount is read-only
# input for `migrate-content`.
ENV HCT_DATA_DIR=/app/data \
    HCT_INDEX_HTML=/app/frontend/index.html \
    UJIN_URL=http://ujin:8901

ENTRYPOINT ["hct-manager"]
CMD ["run"]
