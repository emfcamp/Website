FROM ghcr.io/emfcamp/website-base-dev:latest

COPY pyproject.toml uv.lock Makefile /app/
WORKDIR /app

RUN uv sync \
	&& uv run playwright install-deps \
	&& uv run playwright install chromium

ENV SHELL=/bin/bash
ENTRYPOINT ["./docker/dev_entrypoint.sh"]
