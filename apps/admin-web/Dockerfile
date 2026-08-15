FROM node:24-alpine AS build
WORKDIR /workspace/apps/admin-web
RUN npm install --global pnpm@10.19.0
COPY apps/admin-web/package.json apps/admin-web/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/admin-web/ ./
RUN pnpm build

FROM nginxinc/nginx-unprivileged:1.29-alpine
COPY apps/admin-web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/apps/admin-web/dist /usr/share/nginx/html
EXPOSE 8080
