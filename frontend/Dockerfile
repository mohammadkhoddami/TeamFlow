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
# npm 10 (bundled with node:22-alpine) is known to die with
# "Exit handler never called!" on slow/flaky networks; npm 11 is far more
# robust, so upgrade before installing.
RUN npm install -g npm@11 --no-audit --no-fund

# The lockfile must resolve tarballs from the public registry. Developer
# machines behind a filtered network sometimes regenerate it against a
# regional mirror (e.g. mirror-npm.runflare.com), which GitHub runners
# cannot reach: npm ci then hangs for minutes until npm itself crashes.
# Normalize defensively so the image build never depends on such a mirror.
# The BuildKit cache mount reuses downloaded tarballs across builds and the
# fetch flags ride out transient registry blips instead of failing the build.
RUN --mount=type=cache,target=/root/.npm \
    sed -i 's#https://mirror-npm.runflare.com#https://registry.npmjs.org#g' package-lock.json \
    && npm ci --no-audit --no-fund \
        --fetch-retries=5 \
        --fetch-retry-mintimeout=20000 \
        --fetch-retry-maxtimeout=120000

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
# dist lands in html/flow so nginx can serve it under the /flow/ prefix.
COPY --from=build /app/dist /usr/share/nginx/html/flow

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=5 \
    CMD wget -q -O /dev/null http://127.0.0.1/healthz || exit 1
