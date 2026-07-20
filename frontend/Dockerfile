FROM dhi.io/node:24-dev AS builder

WORKDIR /app

COPY pnpm-lock.yaml package.json ./

RUN corepack enable pnpm

RUN pnpm install --frozen-lockfile

COPY . .

RUN pnpm build

FROM dhi.io/nginx:1.30-alpine

COPY --from=builder --chown=nginx:nginx /app/dist /usr/share/nginx/html

EXPOSE 8080

CMD ["-g", "daemon off;"]
