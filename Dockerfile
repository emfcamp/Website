FROM python:3.7-buster

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      python3-dev libxml2-dev libxslt1-dev libffi-dev git \
      glpk-utils postgresql-client && \
    rm -rf /var/lib/apt/lists/* && \
    pip3 install pipenv

COPY Pipfile Pipfile.lock Makefile /app/
WORKDIR /app

RUN make update

ENV SHELL=/bin/bash
ENTRYPOINT ["./docker/dev_entrypoint.sh"]
