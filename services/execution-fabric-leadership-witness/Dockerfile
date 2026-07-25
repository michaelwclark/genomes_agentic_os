FROM node:22.14.0-alpine3.21 AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY tsconfig.json tsconfig.build.json ./
COPY src ./src
RUN npm run build

FROM node:22.14.0-alpine3.21 AS runtime
ENV NODE_ENV=production
WORKDIR /app
RUN addgroup -S witness && adduser -S -G witness witness
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --ignore-scripts && npm cache clean --force
COPY --from=build /app/dist ./dist
USER witness
EXPOSE 3195
CMD ["node", "dist/src/main.js"]
