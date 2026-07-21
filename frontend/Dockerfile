FROM dhi.io/node:24-dev AS builder

WORKDIR /app

COPY pnpm-lock.yaml package.json ./

RUN corepack enable pnpm \
    && pnpm install --frozen-lockfile

COPY . .

RUN pnpm build


FROM dhi.io/nginx:1.30-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=builder \
    --chown=65532:65532 \
    /app/dist \
    /usr/share/nginx/html

USER 65532

EXPOSE 8080
