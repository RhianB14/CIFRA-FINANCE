FROM node@sha256:f5d1cc40abc10c2843339a2134d07817cf33c405cb16bfd052b0ed790254c3a3

RUN apk add --upgrade --no-cache libcrypto3=3.5.8-r0 libssl3=3.5.8-r0 \
    && mkdir -p /opt/pnpm \
    && wget -qO /tmp/pnpm.tar.gz https://github.com/pnpm/pnpm/releases/download/v11.24.0/pnpm-linux-x64-musl.tar.gz \
    && echo "2fce00e10729d0c1f3836d499b908697fd3cd0832332651fbcee79c0a7442dcb  /tmp/pnpm.tar.gz" | sha256sum -c - \
    && tar -xzf /tmp/pnpm.tar.gz -C /opt/pnpm \
    && rm /tmp/pnpm.tar.gz \
    && ln -s /opt/pnpm/pnpm /usr/local/bin/pnpm \
    && rm -rf /usr/local/lib/node_modules/npm /usr/local/bin/npm /usr/local/bin/npx
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
