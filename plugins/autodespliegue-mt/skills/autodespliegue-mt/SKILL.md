---
name: autodespliegue-mt
description: Prepare a repository so it deploys on Autodespliegue MT, MultitecUA's self-service Cloud Run platform (despliega.multitecua.com). Use whenever the user wants to deploy, publish or host their app "en Multitec", "en el autodespliegue", on Cloud Run through the association, or asks why their Autodespliegue build or service fails. Covers the Dockerfile contract, the $PORT rule, the Firestore database the platform gives each service, secrets, and the preflight script that must pass before pushing.
---

# Autodespliegue MT

MultitecUA members deploy their own services on Google Cloud Run from
**despliega.multitecua.com**. The member connects a GitHub repository in the panel; from
then on, **every push to the chosen branch builds and deploys by itself**. Your job is to
make the repository satisfy the platform's contract, and to prove it with the preflight
script before anything is pushed.

The member has **no access to the Google Cloud console**. Everything they can see or change
is in the panel: build logs, runtime logs, variables, secrets, and the Firestore database.
Do not tell them to run `gcloud`; it will not work for them.

## The contract (what the platform does and does not do)

| The platform does | The repository must |
|---|---|
| Builds the image from **your Dockerfile**, with its own pipeline | Have a Dockerfile (default `./Dockerfile`; another path is set in the panel) |
| Ignores any `cloudbuild.yaml`, `app.yaml`, `Procfile` | Not depend on them |
| Sets the env var `PORT` (8080) and sends traffic there | **Listen on `0.0.0.0:$PORT`**, not on `localhost`, not on a fixed port |
| Scales to zero when idle; starts a container per request burst | Start in under ~10 s, keep no state in memory or on local disk |
| Injects `GOOGLE_CLOUD_PROJECT`, `FIRESTORE_DATABASE` (if enabled) and the member's variables/secrets as env vars | Read configuration from env vars only, never from a committed `.env` |
| Authenticates the container to Firestore by its own identity | **Never** ship a service-account key file; use the client library's default credentials |
| Runs behind IAP (only the owner / all members) unless the Junta approved public | Not implement its own Google login for access control |

Limits per service (the panel shows the member's current quota): 512 MiB or 1 GiB memory,
1 CPU, 2 instances, 5 min request timeout, 120 build minutes a month per member, 5 € a
month per member including Firestore. A build that fails **does not take the service
down**: the previous version keeps serving.

## Workflow

1. **Inspect the repo.** Language, framework, how it starts, which port it uses today,
   whether it stores data, which secrets it needs.
2. **Write or fix the Dockerfile** from `references/dockerfiles.md` (Node, Python, Go,
   static site). Multi-stage, pinned base image tag, non-root user, a `.dockerignore`.
3. **Make it listen on `$PORT`.** This is the number-one cause of "the build passed but the
   service never became ready".
4. **If it stores data, use the Firestore database** the platform gives the service:
   `references/firestore.md`. Read the database name from `FIRESTORE_DATABASE`; without it
   the client goes to `(default)`, which does not exist for you and fails with
   `PERMISSION_DENIED` or `NOT_FOUND`.
5. **Secrets out of git.** Every token or password becomes a *secret* the member adds in
   the panel (Configurar → Variables y secretos). List the names you need for them.
6. **Optional manifest** `autodespliegue.yaml` (see below): the panel pre-fills the form from it.
7. **Run the preflight** and fix until it exits 0:

   ```bash
   python3 <skill-dir>/scripts/check_service.py .           # static checks, seconds
   python3 <skill-dir>/scripts/check_service.py --build .   # also builds and probes it with Docker
   ```

   Exit 0 = ready, 1 = warnings only, 2 = it will fail on the platform. `--build` is the
   real proof: it runs the image with `PORT=8080` (and a different port once, to catch
   hard-coded ports) and requires an HTTP answer.
   Exit 3 means the check could not run (no Docker for `--build`): say so, never report it
   as ready.
8. **Tell the member what to do in the panel**: which branch to connect, which variables and
   secret names to add, whether to enable Firestore, who should have access. Then they push.

## `autodespliegue.yaml` (optional)

```yaml
name: bot-horarios          # 3-30 chars, a-z 0-9 -, becomes bot-horarios.socios.multitecua.com
dockerfile: ./Dockerfile
memory: 512Mi               # 512Mi | 1Gi
access: members             # owner | members | public (public needs Junta approval)
firestore: true
env:                        # plain values, safe to commit
  TZ: Europe/Madrid
secrets:                    # NAMES only; the values are typed in the panel
  - TELEGRAM_TOKEN
```

Never put a secret value in this file. The preflight fails if a key under `env` looks like
a credential.

## When something fails after the push

Ask the member to open the service in the panel:

- **Despliegues** → the failed build's log. Errors in `docker build` are the Dockerfile or
  dependencies; reproduce with `check_service.py --build`.
- **Registros** → runtime logs. `Container failed to start and listen on the port defined by
  the PORT environment variable` = step 3. `PERMISSION_DENIED` on Firestore = step 4, or
  Firestore not enabled for the service.
- **Coste** → if the service is *paused: tope de gasto*, the monthly cap was reached; it
  resumes on the 1st or when the Junta raises it.

## Not supported (do not promise it)

Background work after the response is sent (CPU is throttled between requests), requests or WebSockets
longer than 5 min, local disk that survives a restart, cron jobs, SQL databases, custom
domains, GPUs. If the app needs one of these, say so plainly and suggest asking the Junta.
