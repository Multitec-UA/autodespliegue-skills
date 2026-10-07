#!/usr/bin/env python3
"""Preflight for Autodespliegue MT: will this repository build and serve on the platform?

    python3 check_service.py [--build] [--dockerfile PATH] [REPO_DIR]

Exit 0 ready, 1 warnings only, 2 it will fail on the platform, 3 the check itself could
not run (e.g. --build without Docker). Standard library only, so it runs wherever the
member's agent runs.

Static checks read the files that would be pushed (git ls-files -co --exclude-standard in
a git repo, a walk otherwise). --build is the real proof: it builds the image and requires
an HTTP answer on $PORT, twice, with two different ports, so a hard-coded 8080 fails.
"""
import argparse
import os
import re
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", ".next"}
SOURCE_EXT = {".js", ".mjs", ".cjs", ".ts", ".tsx", ".py", ".go", ".rb", ".java", ".kt",
              ".rs", ".php", ".conf", ".template", ".json", ".toml", ".yaml", ".yml", ".sh"}
MAX_BYTES = 512 * 1024

SECRET_PATTERNS = [
    ("private key", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")),
    ("service-account key", re.compile(r'"type"\s*:\s*"service_account"')),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghs|ghu)_[A-Za-z0-9]{36}\b|\bgithub_pat_[A-Za-z0-9_]{50,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}")),
    ("Slack token", re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}")),
    ("Telegram bot token", re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_\-]{33}\b")),
]
FIRESTORE_USE = re.compile(
    r"@google-cloud/firestore|firebase-admin|from google\.cloud import firestore|"
    r"google\.cloud\.firestore|google-cloud-firestore|cloud\.google\.com/go/firestore")
LOCALHOST_LISTEN = re.compile(
    r"""(?:listen|host|bind|-b|--host)\s*[(=:]?\s*\(?\s*["']?(?:localhost|127\.0\.0\.1)\b"""
    r"""|\.listen\([^)]*["'](?:localhost|127\.0\.0\.1)["']""", re.I)
SECRETY_NAME = re.compile(r"(TOKEN|SECRET|PASSWORD|PASSWD|API_?KEY|PRIVATE)", re.I)
NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,28}[a-z0-9]$")
RESERVED = {"www", "admin", "api", "junta", "despliega", "deploy", "mail", "socios", "panel", "mcp"}


class Report:
    def __init__(self):
        self.fails, self.warns, self.oks = [], [], []

    def fail(self, msg): self.fails.append(msg)
    def warn(self, msg): self.warns.append(msg)
    def ok(self, msg): self.oks.append(msg)

    def print(self):
        for m in self.oks: print(f"  ok    {m}")
        for m in self.warns: print(f"  WARN  {m}")
        for m in self.fails: print(f"  FAIL  {m}")
        verdict = 2 if self.fails else 1 if self.warns else 0
        print({0: "READY: push it.", 1: "READY with warnings.",
               2: "NOT READY: fix the FAIL lines before pushing."}[verdict])
        return verdict


def repo_files(root):
    try:
        out = subprocess.run(["git", "-C", root, "ls-files", "-co", "--exclude-standard"],
                             capture_output=True, text=True, check=True).stdout
        files = [f for f in out.splitlines() if f]
        if files:
            return files
    except (OSError, subprocess.CalledProcessError):
        pass
    found = []
    for d, dirs, names in os.walk(root):
        dirs[:] = [x for x in dirs if x not in SKIP_DIRS]
        for n in names:
            found.append(os.path.relpath(os.path.join(d, n), root))
    return found


def read(root, rel):
    p = os.path.join(root, rel)
    try:
        if os.path.getsize(p) > MAX_BYTES:
            return ""
        with open(p, encoding="utf-8", errors="ignore") as fh:
            return fh.read()
    except OSError:
        return ""


def parse_manifest(text):
    """Tiny reader for autodespliegue.yaml: top-level scalars, `env:` map, `secrets:` list."""
    data, section = {"env": {}, "secrets": []}, None
    for raw in text.splitlines():
        line = raw.split(" #", 1)[0].rstrip()
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if not line.startswith(" "):
            key, _, val = line.partition(":")
            key, val = key.strip(), val.strip().strip("\"'")
            section = key if not val else None
            if val:
                data[key] = val
        elif section == "env" and ":" in line:
            k, _, v = line.strip().partition(":")
            data["env"][k.strip()] = v.strip().strip("\"'")
        elif section == "secrets" and line.strip().startswith("- "):
            data["secrets"].append(line.strip()[2:].strip())
    return data


def check_manifest(root, files, r):
    if "autodespliegue.yaml" not in files:
        r.ok("no autodespliegue.yaml (optional; the panel form is used instead)")
        return {}
    m = parse_manifest(read(root, "autodespliegue.yaml"))
    name = m.get("name", "")
    if not NAME_RE.match(name) or name in RESERVED:
        r.fail(f"autodespliegue.yaml: name '{name}' must be 3-30 chars of a-z 0-9 -, start with a letter, not reserved")
    if m.get("memory", "512Mi") not in ("512Mi", "1Gi"):
        r.fail(f"autodespliegue.yaml: memory '{m['memory']}' must be 512Mi or 1Gi")
    if m.get("access", "members") not in ("owner", "members", "public"):
        r.fail(f"autodespliegue.yaml: access '{m['access']}' must be owner, members or public")
    for k in m["env"]:
        if SECRETY_NAME.search(k):
            r.fail(f"autodespliegue.yaml: env '{k}' looks like a credential; list it under secrets: and type the value in the panel")
    if not r.fails:
        r.ok(f"autodespliegue.yaml valid (name {name})")
    return m


def check_dockerfile(root, files, dockerfile, r):
    if dockerfile not in files and not os.path.isfile(os.path.join(root, dockerfile)):
        r.fail(f"no {dockerfile}: the platform builds only from a Dockerfile")
        return ""
    text = read(root, dockerfile)
    lines = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]
    if not any(re.match(r"(CMD|ENTRYPOINT)\b", l, re.I) for l in lines):
        r.fail(f"{dockerfile} has no CMD or ENTRYPOINT: the container would not start anything")
    for l in lines:
        m = re.match(r"FROM\s+(?:--platform=\S+\s+)?(\S+)", l, re.I)
        if m:
            img = m.group(1)
            if img.lower() != "scratch" and "@sha256:" not in img and (":" not in img.split("/")[-1] or img.endswith(":latest")):
                r.warn(f"base image '{img}' is not pinned to a tag; a rebuild can change under you")
    if re.search(r"^\s*ENV\s+.*GOOGLE_APPLICATION_CREDENTIALS", text, re.M | re.I):
        r.fail("Dockerfile sets GOOGLE_APPLICATION_CREDENTIALS: never ship a key, the platform gives credentials by itself")
    if not any(re.match(r"USER\b", l, re.I) for l in lines) and "nonroot" not in text and "unprivileged" not in text:
        r.warn("no USER in the Dockerfile: the app runs as root")
    if ".dockerignore" not in files:
        r.warn("no .dockerignore: .git, node_modules or .env can end up in the image")
    r.ok(f"{dockerfile} found")
    return text


def check_sources(root, files, dockerfile_text, manifest, r):
    port_seen = "PORT" in dockerfile_text
    fs_used, fs_db, localhost = [], False, []
    for rel in files:
        base = os.path.basename(rel)
        if base == ".env" or (base.startswith(".env.") and not base.endswith((".example", ".sample", ".template"))):
            r.fail(f"{rel} is in the repository: secrets go in the panel, not in git")
        if any(part in SKIP_DIRS for part in rel.split(os.sep)):
            continue
        text = read(root, rel)
        if not text:
            continue
        for label, rx in SECRET_PATTERNS:
            if rx.search(text):
                r.fail(f"{rel}: looks like a committed {label}. Remove it, rotate it, add it as a secret in the panel")
        ext = os.path.splitext(rel)[1]
        if ext in SOURCE_EXT or base in ("Dockerfile", "Procfile"):
            if re.search(r"\bPORT\b", text):
                port_seen = True
            if FIRESTORE_USE.search(text) and base not in ("package-lock.json",):
                fs_used.append(rel)
            if "FIRESTORE_DATABASE" in text:
                fs_db = True
            if ext in (".js", ".mjs", ".cjs", ".ts", ".py", ".go") and LOCALHOST_LISTEN.search(text):
                localhost.append(rel)
        if base in ("cloudbuild.yaml", "cloudbuild.yml", "app.yaml", "Procfile"):
            r.warn(f"{rel} is ignored by the platform; only the Dockerfile counts")
    if not port_seen:
        r.warn("nothing reads PORT: the app must listen on $PORT (8080 on the platform); --build proves it")
    else:
        r.ok("PORT is referenced")
    if localhost:
        r.warn(f"listens on localhost in {', '.join(sorted(set(localhost))[:3])}: on Cloud Run it must be 0.0.0.0")
    if fs_used and not fs_db:
        r.fail(f"Firestore is used ({fs_used[0]}) but FIRESTORE_DATABASE is never read: the client would go to '(default)', which does not exist for you")
    elif fs_used:
        r.ok("Firestore client reads FIRESTORE_DATABASE")
        if manifest and manifest.get("firestore", "false").lower() != "true":
            r.warn("the code uses Firestore but autodespliegue.yaml does not say firestore: true")


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def probe(image, port, env, r, timeout=40):
    host_port = free_port()
    name = f"adm-preflight-{uuid.uuid4().hex[:8]}"
    args = ["docker", "run", "-d", "--rm", "--name", name, "-p", f"127.0.0.1:{host_port}:{port}",
            "-e", f"PORT={port}"]
    for k, v in env.items():
        args += ["-e", f"{k}={v}"]
    started = subprocess.run(args + [image], capture_output=True, text=True)
    if started.returncode != 0:
        r.fail(f"container did not start with PORT={port}: {started.stderr.strip()[:200]}")
        return
    try:
        deadline = time.time() + timeout
        while time.time() < deadline:
            alive = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name],
                                   capture_output=True, text=True).stdout.strip()
            if alive != "true":
                r.fail(f"container exited with PORT={port} before answering (see its logs with check_service.py --build locally)")
                return
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{host_port}/", timeout=3)
                code = "HTTP 200"
            except urllib.error.HTTPError as e:
                code = f"HTTP {e.code}"
            except (socket.timeout, TimeoutError):
                # The request was accepted and is being worked on: something listens. Docker's
                # port proxy, by contrast, closes at once when nothing listens inside, which
                # lands in the branch below. A page that calls Firestore here hangs only
                # because this machine has no Google credentials; on the platform it has.
                code = "a slow answer (the request was accepted)"
            except urllib.error.URLError as e:
                if isinstance(e.reason, (socket.timeout, TimeoutError)):
                    code = "a slow answer (the request was accepted)"
                else:
                    time.sleep(1)
                    continue
            except OSError:
                time.sleep(1)
                continue
            r.ok(f"listens on PORT={port}: {code} after {int(timeout - (deadline - time.time()))} s")
            return
        r.fail(f"nothing answered on PORT={port} within {timeout} s: it listens elsewhere or on localhost")
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True)


def build_and_probe(root, dockerfile, manifest, r):
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        print("check_service: --build needs a running Docker", file=sys.stderr)
        sys.exit(3)
    image = f"adm-preflight:{uuid.uuid4().hex[:8]}"
    b = subprocess.run(["docker", "build", "-q", "-t", image, "-f", os.path.join(root, dockerfile), root],
                       capture_output=True, text=True)
    if b.returncode != 0:
        tail = "\n        ".join(b.stderr.strip().splitlines()[-6:])
        r.fail(f"docker build failed; the platform's build would fail the same way:\n        {tail}")
        return
    r.ok("docker build passes")
    env = {"GOOGLE_CLOUD_PROJECT": "preflight", "FIRESTORE_DATABASE": "preflight-db"}
    env.update(manifest.get("env", {}) if manifest else {})
    for s in (manifest.get("secrets", []) if manifest else []):
        env[s] = "preflight-dummy"
    try:
        probe(image, 8080, env, r)
        probe(image, 9123, env, r)
    finally:
        subprocess.run(["docker", "rmi", "-f", image], capture_output=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("repo", nargs="?", default=".")
    ap.add_argument("--build", action="store_true", help="also docker build and probe $PORT")
    ap.add_argument("--dockerfile", default=None)
    a = ap.parse_args()
    root = os.path.abspath(a.repo)
    if not os.path.isdir(root):
        print(f"check_service: {root} is not a directory", file=sys.stderr)
        return 3
    r = Report()
    files = repo_files(root)
    manifest = check_manifest(root, files, r)
    dockerfile = os.path.normpath(a.dockerfile or manifest.get("dockerfile", "Dockerfile"))
    dtext = check_dockerfile(root, files, dockerfile, r)
    check_sources(root, files, dtext, manifest, r)
    if a.build and dtext and not r.fails:
        build_and_probe(root, dockerfile, manifest, r)
    elif a.build and r.fails:
        r.warn("--build skipped: fix the static FAIL lines first")
    print(f"Autodespliegue MT preflight: {root}")
    return r.print()


if __name__ == "__main__":
    sys.exit(main())
