# Frontend image: Vite build stage + nginx static runtime.
#
# Built by CI and pushed to GHCR; the server only pulls it. The SPA is served
# under /flow/ because the production host already routes arsene.ir/flow to
# this container, with /flow/api and /flow/ws handled by the host nginx.
FROM node:22-alpine AS build

WORKDIR /app

# Baked into the bundle at build time; override per environment.
ARG VITE_BASE_PATH=/flow/
ARG VITE_API_BASE_URL=/flow/api/v1
ARG VITE_WS_BASE_URL=
ENV VITE_BASE_PATH=$VITE_BASE_PATH \
    VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_WS_BASE_URL=$VITE_WS_BASE_URL

COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
# dist lands in html/flow so nginx can serve it under the /flow/ prefix.
COPY --from=build /app/dist /usr/share/nginx/html/flow

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
