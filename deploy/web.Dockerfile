# The Next.js web, built once and served in production mode.
FROM node:20-slim AS build
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci --no-fund --no-audit
COPY apps/web/ ./
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:20-slim
WORKDIR /web
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
COPY --from=build /web ./
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
