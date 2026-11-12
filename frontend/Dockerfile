# Kor Travel Concierge: 기존 full Next build/start 계약을 유지하는 비root 이미지.
FROM node:22.23.1-bookworm-slim@sha256:6c74791e557ce11fc957704f6d4fe134a7bc8d6f5ca4403205b2966bd488f6b3 AS base
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm install --global npm@12.0.1

FROM base AS dependencies
COPY package.json package-lock.json .npmrc ./
COPY vendor ./vendor
RUN npm ci --engine-strict

FROM dependencies AS builder
# NEXT_PUBLIC 값만 client build 입력이다. server-only 인증값은 ARG로 전달하지 않는다.
ARG NEXT_PUBLIC_API_BASE_URL=""
ARG NEXT_PUBLIC_VWORLD_SERVICE_KEY=""
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_PUBLIC_VWORLD_SERVICE_KEY=${NEXT_PUBLIC_VWORLD_SERVICE_KEY}
COPY . .
RUN npm run build

FROM base AS runner
ENV NODE_ENV=production
COPY --from=builder /app/package.json /app/package-lock.json /app/.npmrc ./
COPY --from=builder /app/next.config.mjs /app/postcss.config.mjs /app/tailwind.config.ts /app/tokens.css ./
COPY --from=builder /app/tsconfig.json /app/next-env.d.ts ./
# Manager의 기존 command는 build 후 start한다. standalone 전환이나 runtime 의존성
# pruning 없이 같은 소스·설정·full node_modules를 유지한다.
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/src ./src
COPY --from=builder /app/scripts ./scripts
COPY --from=builder /app/vendor ./vendor
COPY --from=builder --chown=node:node /app/.next ./.next
# 재빌드/ISR/image cache와 Next가 생성·갱신하는 설정 파일만 이미지 안에서 쓸 수 있다.
RUN mkdir -p /app/.next/cache \
    && chown node:node /app /app/.next/cache /app/tsconfig.json /app/next-env.d.ts
USER node
EXPOSE 3000
CMD ["npm", "run", "start"]
