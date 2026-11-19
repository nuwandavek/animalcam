FROM ghcr.io/astral-sh/uv:0.9 AS uv
FROM denoland/deno:bin AS deno
FROM python:3.12-slim
COPY --from=uv /uv /usr/local/bin/uv
COPY --from=deno /deno /usr/local/bin/deno
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 animalcam \
    && mkdir /data && chown animalcam:animalcam /data
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1 STATE_DIR=/data \
    XDG_CACHE_HOME=/data/.cache DENO_DIR=/data/.cache/deno
COPY pyproject.toml ./
RUN uv sync --no-dev
COPY animalcam ./animalcam
COPY cams.toml ./cams.toml
ENV PATH="/app/.venv/bin:$PATH"
USER animalcam
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz',timeout=3)"
ENTRYPOINT ["python", "-m", "animalcam"]
CMD ["serve"]
