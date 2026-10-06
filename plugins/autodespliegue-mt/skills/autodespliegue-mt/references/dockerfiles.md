# Dockerfiles that pass on Autodespliegue MT

Rules shared by all of them: pinned base tag (never `:latest`), multi-stage when there is
a build step, a non-root `USER`, `CMD` in exec form (`["..."]`), and the app listening on
`0.0.0.0:$PORT`. Add the `.dockerignore` at the end, or `node_modules`, `.git` and `.env`
end up in the image.

## Node (Express, Fastify, Next.js standalone, ...)

```dockerfile
FROM node:22-slim AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci --omit=dev

FROM node:22-slim
WORKDIR /app
ENV NODE_ENV=production
COPY --from=deps /app/node_modules ./node_modules
COPY . .
USER node
CMD ["node", "server.js"]
```

```js
const port = process.env.PORT || 8080;
app.listen(port, "0.0.0.0");
```

Next.js: set `output: "standalone"` and run `node .next/standalone/server.js`; it reads
`PORT` and `HOSTNAME` (set `HOSTNAME=0.0.0.0`).

## Python (FastAPI, Flask, Django)

```dockerfile
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
RUN useradd --uid 10001 app
USER app
# FastAPI
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}"]
# Flask / Django: CMD ["sh", "-c", "exec gunicorn -b 0.0.0.0:${PORT:-8080} -w 2 app:app"]
```

`sh -c` is needed only so `${PORT}` expands; keep the `exec`, or signals never reach the
server and every shutdown waits the full 10 s.

## Go

```dockerfile
FROM golang:1.23 AS build
WORKDIR /src
COPY go.* ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -o /app ./cmd/server

FROM gcr.io/distroless/static-debian12:nonroot
COPY --from=build /app /app
CMD ["/app"]
```

```go
port := os.Getenv("PORT"); if port == "" { port = "8080" }
http.ListenAndServe(":"+port, mux)
```

## Static site (Vite, Astro, plain HTML)

```dockerfile
FROM node:22-slim AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginxinc/nginx-unprivileged:1.27-alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
```

`nginx.conf.template` (the official image fills `${PORT}` from the environment at start):

```nginx
server {
  listen ${PORT};
  absolute_redirect off;          # behind Cloud Run, nginx would redirect to http://
  root /usr/share/nginx/html;
  location / { try_files $uri $uri/ /index.html; }
}
```

## `.dockerignore`

```
.git
node_modules
.env
.env.*
__pycache__
*.pyc
dist
.venv
```
