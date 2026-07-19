FROM node:20-alpine

RUN corepack enable

WORKDIR /app

COPY package.json pnpm-lock.yaml* ./
RUN pnpm install

EXPOSE 3000

CMD ["pnpm", "dev"]
