#!/usr/bin/env bash
# Self-test for check_service.py: every rule has a repo that must pass and one that must
# fail. Fixtures are generated in a temp dir, so no fake secret is ever committed.
#   bash tests/run.sh            static checks only (seconds)
#   bash tests/run.sh --build    also the Docker probes (needs Docker, ~1 min)
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
CHECK="python3 $HERE/../scripts/check_service.py"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
pass=0; fail=0

expect() {  # expect <exit> <label> <args...>
  local want=$1 label=$2; shift 2
  local out got; out=$($CHECK "$@" 2>&1); got=$?
  if [ "$got" = "$want" ]; then pass=$((pass+1)); printf '  pass  %s (exit %s)\n' "$label" "$got"
  else fail=$((fail+1)); printf '  FAIL  %s: want exit %s, got %s\n%s\n' "$label" "$want" "$got" "$out"; fi
}

good() {  # good <dir> [server-js-body]: a node app that passes every rule
  mkdir -p "$1"
  cat > "$1/Dockerfile" <<'EOF'
FROM node:22-slim
WORKDIR /app
COPY server.js .
USER node
CMD ["node", "server.js"]
EOF
  printf '.git\nnode_modules\n.env\n' > "$1/.dockerignore"
  printf '%s\n' "${2:-require('http').createServer((q, s) => s.end('ok')).listen(process.env.PORT || 8080, '0.0.0.0');}" > "$1/server.js"
}

echo "static rules"
good "$T/good";                                       expect 0 "good app is ready" "$T/good"
mkdir -p "$T/nodf"; echo x > "$T/nodf/app.py";         expect 2 "no Dockerfile" "$T/nodf"
good "$T/nocmd"; sed -i '/^CMD/d' "$T/nocmd/Dockerfile"; expect 2 "Dockerfile without CMD" "$T/nocmd"
good "$T/tok"; echo "const t = 'ghp_$(printf 'a%.0s' $(seq 36))';" >> "$T/tok/server.js"
                                                      expect 2 "committed GitHub token" "$T/tok"
good "$T/env"; echo "X=1" > "$T/env/.env";             expect 2 "committed .env" "$T/env"
good "$T/envex"; echo "X=" > "$T/envex/.env.example";  expect 0 ".env.example is allowed" "$T/envex"
good "$T/gac"; echo 'ENV GOOGLE_APPLICATION_CREDENTIALS=/k.json' >> "$T/gac/Dockerfile"
                                                      expect 2 "key file in Dockerfile" "$T/gac"
good "$T/fs1"; echo "const { Firestore } = require('@google-cloud/firestore'); const db = new Firestore();" >> "$T/fs1/server.js"
                                                      expect 2 "Firestore without FIRESTORE_DATABASE" "$T/fs1"
good "$T/fs2"; echo "const { Firestore } = require('@google-cloud/firestore'); const db = new Firestore({ databaseId: process.env.FIRESTORE_DATABASE });" >> "$T/fs2/server.js"
                                                      expect 0 "Firestore with FIRESTORE_DATABASE" "$T/fs2"
good "$T/m1"; printf 'name: bot-horarios\nmemory: 512Mi\naccess: members\nenv:\n  TZ: Europe/Madrid\nsecrets:\n  - TELEGRAM_TOKEN\n' > "$T/m1/autodespliegue.yaml"
                                                      expect 0 "valid manifest" "$T/m1"
good "$T/m2"; printf 'name: Bot_Horarios\n' > "$T/m2/autodespliegue.yaml"; expect 2 "manifest bad name" "$T/m2"
good "$T/m3"; printf 'name: admin\n' > "$T/m3/autodespliegue.yaml";        expect 2 "manifest reserved name" "$T/m3"
good "$T/m4"; printf 'name: bot\nmemory: 8Gi\n' > "$T/m4/autodespliegue.yaml"; expect 2 "manifest memory too big" "$T/m4"
good "$T/m5"; printf 'name: bot\nenv:\n  API_KEY: abc\n' > "$T/m5/autodespliegue.yaml"; expect 2 "secret under env:" "$T/m5"
good "$T/w1"; rm "$T/w1/.dockerignore";                expect 1 "no .dockerignore is a warning" "$T/w1"
good "$T/w2"; sed -i 's/node:22-slim/node/' "$T/w2/Dockerfile"; expect 1 "unpinned base image is a warning" "$T/w2"
good "$T/w3"; echo "steps: []" > "$T/w3/cloudbuild.yaml"; expect 1 "cloudbuild.yaml is ignored (warning)" "$T/w3"
good "$T/w4" "require('http').createServer((q, s) => s.end('ok')).listen(process.env.PORT, 'localhost');"
                                                      expect 1 "listen on localhost is a warning" "$T/w4"
good "$T/w5" "app.run(host='127.0.0.1', port=int(os.environ['PORT']))"; mv "$T/w5/server.js" "$T/w5/main.py"
                                                      expect 1 "python host=127.0.0.1 is a warning" "$T/w5"
expect 3 "missing directory" "$T/does-not-exist"

if [ "${1:-}" = "--build" ]; then
  echo "docker probes"
  good "$T/b1";                                                     expect 0 "builds and answers on two ports" --build "$T/b1"
  good "$T/b2" "require('http').createServer((q, s) => s.end('ok')).listen(8080, '0.0.0.0');"
                                                                    expect 2 "hard-coded 8080 fails the second port" --build "$T/b2"
  good "$T/b3" "require('http').createServer((q, s) => s.end('ok')).listen(process.env.PORT, '127.0.0.1');"
                                                                    expect 2 "localhost-only never answers" --build "$T/b3"
  good "$T/b4"; sed -i 's/^USER node/RUN exit 1\nUSER node/' "$T/b4/Dockerfile"
                                                                    expect 2 "failing build" --build "$T/b4"
  good "$T/b5" "process.exit(1);"                                   ; expect 2 "container that exits" --build "$T/b5"
fi

printf '%s passed, %s failed\n' "$pass" "$fail"
[ "$fail" = 0 ]
