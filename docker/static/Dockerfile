#
# Production static content server.
# This serves content in the /static directory, with proxy routing done
# by the host nginx on prod.
#

FROM emfcamp/website:latest AS website
FROM nginx:1.17-alpine

COPY --from=website /app/static /usr/share/nginx/emf-static/static
COPY emf-static.conf /etc/nginx/conf.d/default.conf
