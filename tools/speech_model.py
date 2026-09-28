#!/usr/bin/env python3
"""speech_model.py -- find the Farm Camera speech model, verified, or fetch it once.

    python tools/speech_model.py            -> prints the model folder, or says why not
    python tools/speech_model.py job.m4a "JD568 baler, splice, hose tag"
                                              -> transcribes with word times (JSON to stdout)

Order: a folder that already holds the pinned files wins (packhorse: C:\\Dev\\_models\\speech-base-en-v1).
Otherwise download from the public farm-models repo (pinned commit) in speech_model.json, check every sha256, and keep it
in ~/.cache/farm-models/ so the next run on the same machine does not download again.
A cloud session starts empty each time, so there it downloads once per session (~2 s).
A file whose sha256 does not match is never used.
"""
import hashlib, json, os, sys, urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
SPEC = json.loads((HERE / "speech_model.json").read_text())
FOLDER = f"{SPEC['name']}-{SPEC['version']}"

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()

def good(d):
    d = Path(d)
    for name, want in SPEC["files"].items():
        p = d / name
        if not p.is_file() or p.stat().st_size != want["bytes"] or sha(p) != want["sha256"]:
            return False
    return True

def candidates():
    env = os.environ.get("FARM_SPEECH_MODEL")
    if env:
        yield Path(env)
    for root in (Path("C:/Dev/_models"), HERE.parent.parent / "_models",
                 Path.home() / "mnt/Dev/_models", Path.home() / ".cache/farm-models"):
        yield root / FOLDER

def local_piece(piece):
    """The piece from this repo's own checkout, when the script runs from a clone of
    farm-models -- no download at all."""
    p = HERE.parent / FOLDER / piece["name"]
    try:
        data = p.read_bytes()
    except OSError:
        return None
    if len(data) == piece["bytes"] and hashlib.sha256(data).hexdigest() == piece["sha256"]:
        return data
    return None

def get_piece(piece, tries=5):
    """Download one piece; a proxy can cut a download short without an error, so check size + sha
    and try again (measured 2026-09-28: 3 of 8 raw.githubusercontent.com reads came back short)."""
    data = local_piece(piece)
    if data is not None:
        return data
    for _ in range(tries):
        try:
            with urllib.request.urlopen(SPEC["source_base"] + piece["name"], timeout=60) as r:
                data = r.read()
        except Exception:
            continue
        if len(data) == piece["bytes"] and hashlib.sha256(data).hexdigest() == piece["sha256"]:
            return data
    raise SystemExit(f"REFUSED: {piece['name']} did not download intact after {tries} tries. Not used.")

def fetch(dest):
    dest.mkdir(parents=True, exist_ok=True)
    for name, want in SPEC["files"].items():
        p = dest / name
        if p.is_file() and p.stat().st_size == want["bytes"] and sha(p) == want["sha256"]:
            continue
        tmp = p.with_suffix(p.suffix + ".download")
        pieces = want.get("parts") or [{"name": name, "bytes": want["bytes"], "sha256": want["sha256"]}]
        with open(tmp, "wb") as out:          # model.bin is two pieces: GitHub's 100 MB file limit
            for piece in pieces:
                out.write(get_piece(piece))
        if sha(tmp) != want["sha256"]:
            tmp.unlink()
            raise SystemExit(f"REFUSED: {name} downloaded but its fingerprint is wrong. Not used.")
        tmp.replace(p)

def model_dir():
    for d in candidates():
        if good(d):
            return d
    dest = Path.home() / ".cache/farm-models" / FOLDER
    try:
        fetch(dest)
    except SystemExit:
        raise
    except Exception as e:
        raise SystemExit(f"NO SPEECH MODEL: none found locally, and download failed ({e.__class__.__name__}: {e}).")
    return dest

if __name__ == "__main__":
    d = model_dir()
    if len(sys.argv) < 2:
        print(d); sys.exit(0)
    from faster_whisper import WhisperModel
    m = WhisperModel(str(d), device="cpu", compute_type="int8")
    segs, _ = m.transcribe(sys.argv[1], word_timestamps=True, vad_filter=True, language="en",
                           initial_prompt=(sys.argv[2] if len(sys.argv) > 2 else None))
    words = [{"w": w.word.strip(), "start": round(w.start, 2), "end": round(w.end, 2)}
             for s in segs for w in s.words]
    json.dump({"model": FOLDER, "words": words}, sys.stdout, indent=0)
