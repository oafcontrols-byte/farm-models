# speech-base-en v1

Mirror of the Whisper "base.en" speech-to-text model in CTranslate2 format, for Rieger Farms'
Farm Camera voice notes. No farm data here — third-party model files only.

- Upstream model: OpenAI Whisper base.en — https://github.com/openai/whisper
  "Whisper's code and model weights are released under the MIT License." (upstream README)
  License text: LICENSE in this repo (copied from openai/whisper).
- Converted copy used: https://huggingface.co/Systran/faster-whisper-base.en (listed MIT),
  commit 3d3d5dee26484f91867d81cb899cfcf72b96be6c.
- Runs with: faster-whisper (pip), https://github.com/SYSTRAN/faster-whisper

| file | bytes | sha256 |
|---|---|---|
| model.bin | 145216508 | 2a166925539a16005f14ff328359f9b9adb9dc4fb631bb3b227526862e93e2ef |
| config.json | 2227 | f3bc3821e9fc76a27bae538e11ae5b677dcdd352b4600429ce7951d398569aeb |
| tokenizer.json | 2128466 | 929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df |
| vocabulary.txt | 422309 | ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf |

The files are in the folder `speech-base-en-v1/`. `model.bin` is stored as two pieces (`model.bin.part0` + `model.bin.part1`, joined in that order) because GitHub refuses single files over 100 MB. Joined, it must match the sha256 above.

## tools/

- `speech_model.py` + `speech_model.json` — find this model on the machine, fingerprint-checked,
  or fetch it (from this repo's own checkout if present, else from GitHub) and cache it.
- `voice_job.py` — turns a Farm Camera voice job (`<stamp>_voice.m4a` + `<stamp>_job.json`) into
  a note on each photo: each sentence goes to the photo whose shutter is nearest. Needs
  `pip install faster-whisper`. No farm data lives here; the jobs stay in the private repos.
