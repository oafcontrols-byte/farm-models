#!/usr/bin/env python3
"""voice_job.py -- turn a Farm Camera voice job into a note on each photo.

    python voice_job.py inbox/phone                 # every job waiting there
    python voice_job.py inbox/phone --dry-run       # say what it would write, write nothing
    python voice_job.py inbox/phone --words "PSV, BC12, Rosemount"   # extra words to listen for

WHAT A VOICE JOB IS. Farm Camera's START JOB (CAM 2026.09.28-1) records the mic while
Sean takes photos, and DONE sends three kinds of file into the inbox:

    <start>_voice.m4a      the recording (or _voice_1, _voice_2 ... when the app left
                           the screen mid-job; iOS stops the mic when it does)
    <start>_job.json       when each recording started and when each photo's shutter
                           fired, on the phone's clock
    <shutter>.jpeg         the photos, named for their shutter second as always

WHAT THIS DOES.
  1. Turns the recording into text, on this machine (Whisper base.en, MIT; the model
     is fetched and fingerprint-checked by speech_model.py beside this file).
  2. Cuts the text into sentences with their times.
  3. Gives each sentence to the photo whose shutter is NEAREST it. That rule was
     measured on Sean's own voice on 2026-09-28: he says it as he taps, 4 of 4
     paired right; "words go with the next photo" got it wrong.
  4. Adds the words to each photo's note file, `<photo>.txt`, under a line that says
     they came from the recording and were NOT checked -- the same file the camera
     writes typed captions and GPS into, so file_photo.py shows them with nothing new.
  5. Writes the whole transcript beside the recording and moves the recording, the
     time file and the transcript out of the inbox (docs/evidence/voice/ when the repo
     has docs/evidence, else inbox/voice/), so the inbox again holds only photos.

WHAT IT DOES NOT DO. It does not decide what a photo shows, and it never fixes a word.
Doubts are printed and written into the note:
  - a sentence nearly as close to the photo before or after (which photo it belongs to
    is a guess),
  - a photo nothing was said near,
  - words Whisper was unsure of (low confidence).
Those are for the session to ask Sean about, not to settle by guessing.

Needs: pip install faster-whisper   (the model itself comes via speech_model.py)
"""
import argparse, json, re, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

DEFAULT_WORDS = ("John Deere, baler, net wrap, harness, connector, splice, hose, hose tag, "
                 "crimp, pickup, serial plate, hydraulic, PTO, bearing, belt, transmitter, "
                 "calibration, setpoint, psi, kPa")
NEAR_S = 10.0        # a sentence further than this from every shutter is a job note
AMBIG_S = 1.5        # second-nearest photo within this of the nearest: flagged
UNSURE_LOGPROB = -1.0


def sentences_of(words, start_ms):
    """[{text, a, b, unsure}] with a/b in epoch ms, cut at . ? ! -- or at a pause
    over 1.2 s, because a man talking while he works does not always finish one."""
    out, cur = [], []
    def flush():
        if cur:
            text = "".join(w["w"] for w in cur).strip()
            if text:
                out.append({"text": text, "a": start_ms + cur[0]["s"] * 1000,
                            "b": start_ms + cur[-1]["e"] * 1000,
                            "unsure": [w["w"].strip() for w in cur if w["p"] < 0.35]})
            cur.clear()
    prev_end = None
    for w in words:
        if cur and prev_end is not None and w["s"] - prev_end > 1.2:
            flush()
        cur.append(w)
        prev_end = w["e"]
        if re.search(r"[.?!]$", w["w"].strip()):
            flush()
    flush()
    return out


def transcribe(audio, prompt):
    import speech_model
    d = speech_model.model_dir()
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        raise SystemExit("Needs faster-whisper: pip install faster-whisper")
    m = WhisperModel(str(d), device="cpu", compute_type="int8")
    segs, _ = m.transcribe(str(audio), word_timestamps=True, vad_filter=True,
                           language="en", initial_prompt=prompt)
    words = []
    for s in segs:
        for w in (s.words or []):
            words.append({"w": w.word, "s": w.start, "e": w.end, "p": w.probability})
    return words


def dist(sent, t):
    if sent["a"] <= t <= sent["b"]:
        return 0.0
    return min(abs(t - sent["a"]), abs(t - sent["b"])) / 1000.0


# Words that run a job rather than describe a photo -- kept in the transcript,
# left off the notes.
FILLER = {"done", "done.", "okay", "okay.", "ok", "ok.", "mark", "mark.", "next", "next.",
          "okay, mark.", "okay mark", "okay, done.", "that's it.", "that's it"}


def pair(sents, photos):
    """Each sentence -> the nearest shutter within NEAR_S, else a job note."""
    notes = {p["file"]: [] for p in photos}
    job_notes, doubts = [], []
    for s in sents:
        if s["text"].strip().lower() in FILLER:
            s["filler"] = True
            continue
        if not photos:
            job_notes.append(s); continue
        ds = sorted((dist(s, p["shutter_ms"]), i) for i, p in enumerate(photos))
        d0, i0 = ds[0]
        if d0 > NEAR_S:
            job_notes.append(s); continue
        p = photos[i0]
        s["photo"] = p["file"]
        if len(ds) > 1 and ds[1][0] - d0 < AMBIG_S:
            other = photos[ds[1][1]]["file"]
            s["doubt"] = "could belong to %s instead" % other
            doubts.append('%s: "%s" -- could belong to %s instead' % (p["file"], s["text"], other))
        notes[p["file"]].append(s)
    for p in photos:
        if not notes[p["file"]]:
            doubts.append("%s: nothing was said near this photo" % p["file"])
    return notes, job_notes, doubts


def note_text(sents):
    lines = ["Said while taking it (from the voice recording, NOT checked):"]
    for s in sents:
        line = "  " + s["text"]
        if s.get("doubt"):
            line += "   [? %s]" % s["doubt"]
        if s["unsure"]:
            line += "   [hard to hear: %s]" % ", ".join(s["unsure"])
        lines.append(line)
    return "\n".join(lines) + "\n"


def done_dir(folder):
    repo = folder.resolve()
    for up in [repo] + list(repo.parents):
        if (up / ".git").exists():
            if (up / "docs" / "evidence").is_dir():
                return up / "docs" / "evidence" / "voice"
            break
    return folder.parent / "voice"


def run_job(folder, jpath, words, dry):
    man = json.loads(jpath.read_text(encoding="utf-8"))
    photos = [p for p in man.get("photos", []) if (folder / p["file"]).is_file()]
    missing = [p["file"] for p in man.get("photos", []) if not (folder / p["file"]).is_file()]
    prompt = ", ".join(x for x in [DEFAULT_WORDS, words] if x)
    sents, heard = [], []
    for r in man.get("recordings", []):
        a = folder / r["file"]
        if not a.is_file():
            heard.append("recording %s is not in the folder" % r["file"]); continue
        ws = transcribe(a, prompt)
        sents += sentences_of(ws, r["start_ms"])
    sents.sort(key=lambda s: s["a"])
    notes, job_notes, doubts = pair(sents, photos)
    doubts += ["%s is named in the job but not in the folder (filed or deleted already?)" % m for m in missing]
    doubts += heard
    doubts += ['%s: hard to hear -- %s' % (s.get("photo", "job"), ", ".join(s["unsure"]))
               for s in sents if s["unsure"] and not s.get("filler")]

    stem = jpath.name[:-len("_job.json")]
    print("== voice job %s  (%d photo(s), %d sentence(s), ended: %s)" %
          (stem, len(photos), len(sents), man.get("ended", "?")))
    for p in photos:
        print("  %s" % p["file"])
        for s in notes[p["file"]]:
            print("      \"%s\"%s" % (s["text"], ("   [? %s]" % s["doubt"]) if s.get("doubt") else ""))
    if job_notes:
        print("  said away from any photo (job notes):")
        for s in job_notes:
            print("      \"%s\"" % s["text"])
    if doubts:
        print("  ASK SEAN / CHECK:")
        for d in doubts:
            print("    - " + d)

    trans = ["Voice job %s -- transcript (Whisper base.en, NOT checked)" % stem,
             "started %s, ended: %s" % (man.get("started_local", "?"), man.get("ended", "?")), ""]
    for s in sents:
        trans.append("[%s] %s%s" % ("filler" if s.get("filler") else s.get("photo", "job note"), s["text"],
                                    ("   [? %s]" % s["doubt"]) if s.get("doubt") else ""))
    if doubts:
        trans += ["", "Doubts:"] + ["  - " + d for d in doubts]
    if dry:
        return 0
    for p in photos:
        if not notes[p["file"]]:
            continue
        np = (folder / p["file"]).with_suffix(".txt")
        old = np.read_text(encoding="utf-8") if np.is_file() else ""
        if "from the voice recording" in old:
            continue                          # run twice: do not say it twice
        np.write_text((old.rstrip("\n") + "\n" if old.strip() else "") + note_text(notes[p["file"]]),
                      encoding="utf-8")
    dd = done_dir(folder)
    dd.mkdir(parents=True, exist_ok=True)
    (dd / (stem + "_voice_transcript.txt")).write_text("\n".join(trans) + "\n", encoding="utf-8")
    for r in man.get("recordings", []):
        a = folder / r["file"]
        if a.is_file():
            shutil.move(str(a), str(dd / a.name))
    if job_notes:
        # words not near any photo stay in front of whoever files the photos
        (folder / (stem + "_job_notes.txt")).write_text(
            "Said during voice job %s away from any photo (NOT checked):\n%s" %
            (stem, "".join("  %s\n" % s["text"] for s in job_notes)), encoding="utf-8")
    shutil.move(str(jpath), str(dd / jpath.name))
    print("  notes written; recording, time file and transcript moved to %s" % dd)
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("folder", nargs="?", default="inbox/phone")
    ap.add_argument("--words", default="", help="extra words to listen for, comma separated")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    folder = Path(a.folder)
    jobs = sorted(folder.glob("*_job.json"))
    if not jobs:
        print("No voice job in %s." % folder)
        return 0
    for j in jobs:
        run_job(folder, j, a.words, a.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
