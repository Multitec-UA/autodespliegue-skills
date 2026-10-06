# Firestore on Autodespliegue MT

When the member ticks **Base de datos Firestore** for a service, the platform creates **one
Firestore database (Native mode) for that service only**, in `europe-west1`, and gives the
service's own identity read/write access to it and to nothing else. The container gets:

| Env var | Value |
|---|---|
| `GOOGLE_CLOUD_PROJECT` | `mt-autodespliegue` |
| `FIRESTORE_DATABASE` | e.g. `bot-horarios-db` (never `(default)`) |

Credentials come from the runtime automatically (Application Default Credentials). **No
key file, no `GOOGLE_APPLICATION_CREDENTIALS`.**

## The one mistake that breaks it

Every client library connects to the database called `(default)` unless told otherwise.
That database does not exist for you, so the app starts fine and fails on the first query
with `PERMISSION_DENIED` or `NOT_FOUND`. **Always pass the database id from
`FIRESTORE_DATABASE`.** The preflight checks this.

## Node — `@google-cloud/firestore` (or `firebase-admin`)

```js
import { Firestore } from "@google-cloud/firestore";
const db = new Firestore({ databaseId: process.env.FIRESTORE_DATABASE });
await db.collection("reservas").add({ aula: "L12", at: new Date() });
```

`firebase-admin`: `getFirestore(initializeApp(), process.env.FIRESTORE_DATABASE)`.

## Python — `google-cloud-firestore` >= 2.12

```python
import os
from google.cloud import firestore
db = firestore.Client(database=os.environ["FIRESTORE_DATABASE"])
db.collection("reservas").add({"aula": "L12"})
```

## Go — `cloud.google.com/go/firestore`

```go
db, err := firestore.NewClientWithDatabase(ctx, os.Getenv("GOOGLE_CLOUD_PROJECT"), os.Getenv("FIRESTORE_DATABASE"))
```

## What it is and is not

- **Server side only.** The browser must not talk to Firestore directly (no Firebase web
  SDK, no security rules): your backend does every read and write. Access control is your
  code plus IAP in front of the service.
- **Billed from the first read** (the free tier covers only a project's `(default)`
  database). For a small app it is cents a month, counted in the member's 5 € cap. Avoid
  reading whole collections on every request; use queries with `limit`.
- **Backups:** the platform takes a daily backup kept 7 days. Restoring is asked from the
  panel.
- **Deleting the service** asks whether to keep the database; if not, it is exported and
  deleted after 30 days.
- **Looking at the data:** the panel has a read-only explorer (collections, documents) and
  an export to JSON. Writes go through your app.

## Local development

Run the emulator and point the client at it; no Google account needed:

```bash
docker run --rm -p 8085:8085 gcr.io/google.com/cloudsdktool/google-cloud-cli:emulators \
  gcloud emulators firestore start --host-port=0.0.0.0:8085
export FIRESTORE_EMULATOR_HOST=localhost:8085 GOOGLE_CLOUD_PROJECT=demo-local FIRESTORE_DATABASE=demo-db
```
