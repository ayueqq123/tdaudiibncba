FROM guergeiro/pnpm:lts-latest-slim AS build

WORKDIR /fba_ui

COPY . .

# CI=true: is-ci 命中后 prepare 里的 lefthook install 被短路(构建镜像无 git)
ENV CI=true
RUN pnpm install \
    && pnpm build

FROM nginx

COPY scripts/deploy/nginx.conf /etc/nginx/nginx.conf

COPY --from=build /fba_ui/apps/web-antdv-next/dist /var/www/fba_ui

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
