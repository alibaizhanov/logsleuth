"""First-run bootstrap: make `pip install logsleuth` enough.

Local inference needs two things that are not Python packages — a runtime and
model weights. Asking the user to go install them by hand is where a tool like
this loses most of its would-be users, so logsleuth arranges both itself, with
consent, inside its own directory. Nothing is installed system-wide, nothing
needs admin rights, and removing ~/.logsleuth undoes all of it.

Order of preference, so we never download what is already there:
  1. an Ollama server already running (yours, untouched)
  2. an ollama binary on PATH or in the usual install locations
  3. a runtime we downloaded earlier into ~/.logsleuth
  4. ask, then download one
"""
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request

HOME = os.path.expanduser("~/.logsleuth")
BIN = os.path.join(HOME, "bin")
DEFAULT_URL = os.environ.get("LOGSLEUTH_OLLAMA_URL", "http://localhost:11434")

# Model choice follows available memory: a model that swaps is worse than a
# smaller model that fits.
MODELS = [(10, "qwen3:4b", 2.4), (24, "qwen3:8b", 5.2), (10 ** 9, "qwen3:14b", 9.3)]

_GH = "https://github.com/ollama/ollama/releases/latest/download"

# Only the macOS tarball is a format the standard library can unpack (gzip), and
# at 139MB it is a reasonable thing to fetch unattended. The Linux builds ship as
# .tar.zst around 1.4GB because they bundle CUDA/ROCm, and stdlib has no zstd
# before Python 3.14 — so there we lean on the system `tar`, and if that cannot
# do zstd either we hand the user one command instead of guessing.
RELEASES = {
    ("Darwin", "arm64"): (f"{_GH}/ollama-darwin.tgz", 139),
    ("Darwin", "x86_64"): (f"{_GH}/ollama-darwin.tgz", 139),
    ("Linux", "x86_64"): (f"{_GH}/ollama-linux-amd64.tar.zst", 1356),
    ("Linux", "aarch64"): (f"{_GH}/ollama-linux-arm64.tar.zst", 1471),
}

MANUAL = {
    "Windows": "install Ollama from https://ollama.com/download",
    "Linux": "run: curl -fsSL https://ollama.com/install.sh | sh",
    "Darwin": "install Ollama from https://ollama.com/download",
}


def total_ram_gb():
    try:
        if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names:
            return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
    except (ValueError, OSError):
        pass
    try:
        out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True)
        return int(out.stdout.strip()) / 1e9
    except Exception:
        return 16.0


def pick_model():
    ram = total_ram_gb()
    for ceiling, name, size in MODELS:
        if ram < ceiling:
            return name, size
    return MODELS[-1][1], MODELS[-1][2]


def server_alive(url=DEFAULT_URL, timeout=2):
    try:
        with urllib.request.urlopen(f"{url}/api/version", timeout=timeout):
            return True
    except Exception:
        return False


def find_binary():
    """An ollama we can start: on PATH, in the usual places, or one we fetched."""
    found = shutil.which("ollama")
    if found:
        return found
    candidates = [
        os.path.join(BIN, "ollama"),
        os.path.expanduser("~/Applications/Ollama.app/Contents/Resources/ollama"),
        "/Applications/Ollama.app/Contents/Resources/ollama",
        "/usr/local/bin/ollama",
    ]
    hit = next((c for c in candidates if os.path.isfile(c) and os.access(c, os.X_OK)), None)
    if hit:
        return hit
    app = os.path.join(HOME, "app")
    return _find_ollama_in(app) if os.path.isdir(app) else None


def start_server(binary, url=DEFAULT_URL, wait=25):
    os.makedirs(HOME, exist_ok=True)
    log = open(os.path.join(HOME, "runtime.log"), "ab")
    env = dict(os.environ, OLLAMA_HOST=url.split("//", 1)[-1])
    subprocess.Popen([binary, "serve"], stdout=log, stderr=log, env=env,
                     start_new_session=True)
    for _ in range(wait * 2):
        if server_alive(url, timeout=1):
            return True
        time.sleep(0.5)
    return False


def _ssl_context():
    """A context that can actually verify certificates.

    A python.org install on macOS ships with an empty trust store until the user
    runs Install Certificates.command, so the default context fails on every
    HTTPS download. certifi is usually sitting in site-packages anyway; use it
    when the default store is empty rather than making the user go fix Python.
    """
    import ssl
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0):
        return ctx
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ctx


def _curl(url, dest, say, label):
    """Last resort: the system curl, which trusts the OS keychain."""
    if not shutil.which("curl"):
        return False
    say(f"downloading {label} (via curl)…")
    p = subprocess.run(["curl", "-fL", "--progress-bar", "-o", dest, url])
    return p.returncode == 0 and os.path.getsize(dest) > 0


def _download(url, dest, say, label):
    """Stream a download with a progress line."""
    try:
        return _download_stream(url, dest, say, label)
    except urllib.error.URLError as e:
        if not isinstance(getattr(e, "reason", None), OSError) and "SSL" not in str(e):
            raise
        if _curl(url, dest, say, label):
            return
        raise


def _download_stream(url, dest, say, label):
    say(f"downloading {label}…")
    with urllib.request.urlopen(url, timeout=60, context=_ssl_context()) as resp, open(dest, "wb") as out:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        last = 0.0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if total and time.time() - last > 0.4:
                last = time.time()
                pct = 100 * done / total
                bar = "█" * int(pct / 4) + "░" * (25 - int(pct / 4))
                say(f"  {label} {bar} {pct:3.0f}%  ({done/1e6:.0f}/{total/1e6:.0f} MB)", cr=True)
    say("", cr=False)


def _unpack(archive, into, say):
    """Unpack via stdlib where possible, else the system tar (needed for .tar.zst)."""
    os.makedirs(into, exist_ok=True)
    if archive.endswith(".zip"):
        import zipfile
        with zipfile.ZipFile(archive) as z:
            z.extractall(into)
        return True
    if archive.endswith((".tgz", ".tar.gz")):
        import tarfile
        with tarfile.open(archive) as t:
            t.extractall(into)
        return True
    for flags in (["--zstd"], ["--use-compress-program", "unzstd"]):
        try:
            p = subprocess.run(["tar", "-x"] + flags + ["-f", archive, "-C", into],
                               capture_output=True)
            if p.returncode == 0:
                return True
        except OSError:
            break
    say("this system's tar cannot unpack .tar.zst archives")
    return False


def _find_ollama_in(tree):
    for root, _, names in os.walk(tree):
        for n in names:
            if n == "ollama":
                path = os.path.join(root, n)
                if os.path.isfile(path):
                    os.chmod(path, 0o755)
                    return path
    return None


def install_runtime(say):
    entry = RELEASES.get((platform.system(), platform.machine()))
    if not entry:
        return None
    url, _ = entry
    app = os.path.join(HOME, "app")
    os.makedirs(HOME, exist_ok=True)
    archive = os.path.join(HOME, os.path.basename(url))
    try:
        _download(url, archive, say, "runtime")
        ok = _unpack(archive, app, say)
    except (urllib.error.URLError, OSError) as e:
        say(f"could not download the runtime: {e}")
        return None
    except Exception as e:
        say(f"could not unpack the runtime: {e}")
        return None
    finally:
        try:
            os.unlink(archive)
        except OSError:
            pass
    return _find_ollama_in(app) if ok else None


def have_model(model, url=DEFAULT_URL):
    try:
        with urllib.request.urlopen(f"{url}/api/tags", timeout=5) as r:
            tags = [m["name"] for m in json.loads(r.read()).get("models", [])]
    except Exception:
        return False, []
    return (model in tags or f"{model}:latest" in tags), tags


def pull_model(model, say, url=DEFAULT_URL):
    req = urllib.request.Request(f"{url}/api/pull",
                                 data=json.dumps({"name": model}).encode(),
                                 headers={"Content-Type": "application/json"})
    last = 0.0
    with urllib.request.urlopen(req, timeout=3600) as resp:
        for raw in resp:
            if not raw.strip():
                continue
            try:
                ev = json.loads(raw)
            except ValueError:
                continue
            if ev.get("error"):
                say(f"model download failed: {ev['error']}")
                return False
            total, done = ev.get("total"), ev.get("completed")
            if total and done and time.time() - last > 0.4:
                last = time.time()
                pct = 100 * done / total
                bar = "█" * int(pct / 4) + "░" * (25 - int(pct / 4))
                say(f"  model {bar} {pct:3.0f}%  ({done/1e9:.1f}/{total/1e9:.1f} GB)", cr=True)
    say("", cr=False)
    return True


def _stderr(msg, cr=False):
    sys.stderr.write(("\r" if cr else "") + msg + ("" if cr else "\n"))
    sys.stderr.flush()


def ensure(model=None, say=_stderr, ask=None, url=DEFAULT_URL):
    """Return (model_name, ready). Sets up runtime and weights if needed."""
    auto_model, size = pick_model()
    model = model or auto_model

    if not server_alive(url):
        binary = find_binary()
        if binary is None:
            entry = RELEASES.get((platform.system(), platform.machine()))
            if not entry:
                say("no automatic setup for this platform — "
                    + MANUAL.get(platform.system(), MANUAL["Darwin"]))
                return model, False
            rt_mb = entry[1]
            if ask and not ask(
                    "logsleuth runs the model on this machine, so your logs never leave it.\n"
                    f"  It needs a local runtime ({rt_mb/1024:.1f}GB) and the model "
                    f"{model} ({size:.1f}GB).\n"
                    "  Both go in ~/.logsleuth and can be deleted later.\n"
                    "  Set this up now?"):
                return model, False
            binary = install_runtime(say)
            if binary is None:
                say("automatic setup failed — "
                    + MANUAL.get(platform.system(), MANUAL["Darwin"]))
                return model, False
        if not start_server(binary, url):
            say("could not start the local runtime")
            return model, False

    ok, tags = have_model(model, url)
    if not ok:
        # Honour whatever the user already pulled rather than making them wait for
        # a download. Embedding models cannot answer a prompt, so skip those.
        usable = [t for t in tags if not any(w in t.lower() for w in
                                             ("embed", "rerank", "bge", "minilm"))]
        if usable:
            say(f"using the model you already have: {usable[0]}")
            return usable[0], True
        if ask and not ask(f"Download the model {model} (~{size:.1f}GB) now?"):
            return model, False
        if not pull_model(model, say, url):
            return model, False
    return model, True
