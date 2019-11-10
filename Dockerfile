FROM emfcamp/website-base:latest

COPY Pipfile Pipfile.lock Makefile /app/
WORKDIR /app

RUN pipenv sync --dev && pipenv run pyppeteer-install

ENV SHELL=/bin/bash
ENTRYPOINT ["./docker/dev_entrypoint.sh"]
