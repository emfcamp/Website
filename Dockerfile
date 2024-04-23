FROM ghcr.io/emfcamp/website-base-dev:latest

COPY pyproject.toml poetry.lock Makefile /app/
WORKDIR /app

RUN poetry install \
	&& poetry run playwright install-deps \
	&& poetry run playwright install chromium

ENV SHELL=/bin/bash
ENTRYPOINT ["./docker/dev_entrypoint.sh"]
