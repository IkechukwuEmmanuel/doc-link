# SpacePad frontend — production image (multi-stage).
#
# Stage 1 builds the Vite app (tsc -b && vite build → /app/dist). Stage 2 serves
# the static output with nginx (SPA fallback + /api reverse proxy with WebSocket
# upgrade), NOT the Vite dev server.

# ---- builder ---------------------------------------------------------------- #
FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# ---- runtime ---------------------------------------------------------------- #
FROM nginx:1.27-alpine AS runtime
# `envsubst` (in this image) renders the template at startup so the backend
# upstream is configurable per environment without rebuilding.
ENV BACKEND_URL=http://backend:8000
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
EXPOSE 80
# nginx:alpine's entrypoint runs envsubst over /etc/nginx/templates/*.template.
