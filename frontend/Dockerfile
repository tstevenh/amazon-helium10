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

RUN npm run build

EXPOSE 3000

# Production server. Local development overrides this with `npm run dev` via
# docker-compose.override.yml, which Compose applies automatically.
CMD ["npm", "run", "start"]
