# Compile and assemble the pure-JavaScript production dependency tree on the
# native builder architecture. Running npm through QEMU made cross-platform
# releases nondeterministically crash with SIGILL before an image existed.
FROM --platform=$BUILDPLATFORM node:22.14.0-alpine3.21 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY tsconfig.json tsconfig.build.json ./
COPY src ./src
RUN npm run build \
  && npm prune --omit=dev --ignore-scripts \
  && npm cache clean --force

FROM node:22.14.0-alpine3.21 AS runtime
ENV NODE_ENV=production
WORKDIR /app
ARG WITNESS_UID=3195
ARG WITNESS_GID=3195
RUN addgroup -S -g "$WITNESS_GID" witness \
  && adduser -S -D -H -u "$WITNESS_UID" -G witness witness \
  && mkdir -p /var/lib/execution-fabric-witness \
  && chown witness:witness /var/lib/execution-fabric-witness \
  && chmod 0700 /var/lib/execution-fabric-witness
COPY package.json package-lock.json ./
COPY --from=build /app/node_modules ./node_modules
COPY --from=build /app/dist ./dist
USER witness
EXPOSE 3195
VOLUME ["/var/lib/execution-fabric-witness"]
CMD ["node", "dist/src/main.js"]
