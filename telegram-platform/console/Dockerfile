# ---------- build ----------
FROM node:20-alpine AS build
RUN corepack enable && corepack prepare pnpm@10.34.5 --activate
WORKDIR /app
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

# ---------- serve ----------
FROM nginx:1.27-alpine
COPY scripts/deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /var/www/console
EXPOSE 80
