FROM ghcr.io/emfcamp/website-base-dev:latest

COPY pyproject.toml poetry.lock Makefile /app/
WORKDIR /app

RUN poetry install && poetry run pyppeteer-install

ENV SHELL=/bin/bash
ENTRYPOINT ["./docker/dev_entrypoint.sh"]
