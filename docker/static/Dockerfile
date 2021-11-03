#
# Production static content server.
# This serves content in the /static directory, with proxy routing done
# by the host nginx on prod.
#

FROM ghcr.io/emfcamp/website:latest AS website
FROM nginx:1.17-alpine

COPY --from=website /app/static /usr/share/nginx/emf-static/static

# Create a webp version of all images, served automatically by nginx.
#
# You might argue that it's more obvious to do this with gulp, and you might be right,
# but npm wanted to compile libwebp from source and I don't have time for this bullshit.
RUN apk --no-cache add libwebp-tools && \
	find /usr/share/nginx/emf-static/static \( -name '*.jpg' -o -name '*.png' \) -print0 | xargs -0 -I '{}' -P 3 cwebp -quiet '{}' -o '{}.webp' && \
	apk --no-cache del libwebp-tools

COPY emf-static.conf /etc/nginx/conf.d/default.conf
