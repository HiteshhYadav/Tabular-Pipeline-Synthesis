# The web image: the production build of the React app, served by nginx,
# which also proxies /api to the API container. One origin for both, so the
# browser needs no CORS and the API port is never exposed.

FROM node:22-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Same-origin API. Set in the environment so it outranks any .env file.
ENV VITE_API_BASE=/api
RUN npm run build

FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
HEALTHCHECK --interval=15s --timeout=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/healthz >/dev/null || exit 1
