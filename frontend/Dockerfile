FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm install

COPY . .

# NEXT_PUBLIC_* values are inlined into the browser bundle at BUILD time, not
# read at runtime, so this must be present before `npm run build`.
# /backend is a same-origin path the Next.js rewrite proxies to the API.
ARG NEXT_PUBLIC_API_URL=/backend
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL

# API_URL is needed at BUILD time too, and that is not obvious. `rewrites()` in
# next.config.js runs during `npm run build`, and Next serialises the resulting
# destination into .next/routes-manifest.json. `npm run start` reads that
# manifest and never re-evaluates the config, so setting API_URL only in
# docker-compose `environment:` is too late — the destination is already frozen.
#
# Leaving it unset here baked in the `http://localhost:8000` fallback, which
# inside this container points at nothing: every /backend/* call returned 500
# while the API itself was healthy and showed no request at all in its log.
ARG API_URL=http://api:8000
ENV API_URL=$API_URL

RUN npm run build

EXPOSE 3000

# Production server. Local development overrides this with `npm run dev` via
# docker-compose.override.yml, which Compose applies automatically.
CMD ["npm", "run", "start"]
