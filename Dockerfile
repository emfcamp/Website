FROM emfcamp/website-base:latest

COPY Pipfile Pipfile.lock Makefile /app/
WORKDIR /app

RUN make update
RUN pipenv run pyppeteer-install

ENV SHELL=/bin/bash
ENTRYPOINT ["./docker/dev_entrypoint.sh"]
