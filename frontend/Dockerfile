FROM node:24-alpine AS builder

WORKDIR /app

COPY pnpm-lock.yaml package.json ./

RUN corepack enable pnpm

RUN pnpm install --frozen-lockfile

COPY . .

RUN pnpm build

FROM nginx:1.29-alpine

COPY --from=builder /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
