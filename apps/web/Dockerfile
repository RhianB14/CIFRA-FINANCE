FROM node@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32

RUN npm install --global npm@12.0.2 && npm install --global pnpm@11.24.0
RUN apk add --upgrade --no-cache libcrypto3=3.5.8-r0 libssl3=3.5.8-r0
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
RUN adduser -D -u 10001 cifra && chown -R cifra /workspace/apps/web
USER cifra
EXPOSE 3000
CMD ["pnpm", "--filter", "@cifra/web", "dev"]
