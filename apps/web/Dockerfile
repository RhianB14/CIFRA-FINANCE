FROM node:22-bookworm-slim

RUN npm install --global pnpm@11.24.0
WORKDIR /workspace
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml turbo.json tsconfig.base.json ./
COPY apps/web/package.json apps/web/package.json
COPY apps/mobile/package.json apps/mobile/package.json
COPY packages/shared-types/package.json packages/shared-types/package.json
COPY packages/api-client/package.json packages/api-client/package.json
COPY packages/domain-rules/package.json packages/domain-rules/package.json
RUN pnpm install --frozen-lockfile
COPY apps/web apps/web
COPY packages packages
EXPOSE 3000
CMD ["pnpm", "--filter", "@cifra/web", "dev"]
