FROM node:22-alpine

RUN corepack enable

WORKDIR /app

COPY package.json pnpm-lock.yaml* .npmrc pnpm-workspace.yaml ./
RUN pnpm install

EXPOSE 3000

CMD ["pnpm", "dev"]
