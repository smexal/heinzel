# Build context: repository root (pnpm workspace).
FROM node:22-alpine AS build
RUN npm install -g pnpm@10.28.0
WORKDIR /app
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml ./
COPY apps/web/package.json apps/web/
RUN pnpm install --frozen-lockfile --filter web...
COPY apps/web apps/web
RUN pnpm --filter web build

# The adapter-node build bundles everything the server imports (the web app has no runtime
# dependencies yet). Once it gets one, copy a `pnpm --filter web deploy --prod` here instead.
FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=3000 \
    HOST_HEADER=x-forwarded-host PROTOCOL_HEADER=x-forwarded-proto \
    ADDRESS_HEADER=x-forwarded-for XFF_DEPTH=1
COPY --from=build /app/apps/web/package.json ./
COPY --from=build /app/apps/web/build ./build
USER node
EXPOSE 3000
CMD ["node", "build"]
