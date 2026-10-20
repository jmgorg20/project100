# Fix G: sound effects on the real export

Run on the user's Windows export (`export.mp4`) with the Groq-format words, the preset and the
pin instruction, through `editor.py ai-edit` exactly as the app runs it, twice:

```
python scripts/acceptance.py RUNS/g_auto --cli --spaced-names --video export.mp4 \
  --words tests/data/realclip/groq_words.json --cues tests/data/realclip/groq_cues_spaced.json \
  --preset premium_editorial_viral --instruction-file tests/data/realclip/instruction_pin.txt
python scripts/acceptance.py RUNS/g_off ... --sfx off
python scripts/sfx_levels.py RUNS docs/acceptance/realclip/g
```

- `report.md`: the cue check (11 passed) and *What the AI did* ("Sound effects: 35, synced to the
  graphics...").
- `levels.md`: each sound, measured in the exported audio (with sound effects minus without,
  aligned to the sample and gain-matched): 35 of 35 above the codec noise floor, peaks -16 to
  -29 dB, under a voice of about -6.5 dB RMS.
- `waveform.png`: the voice, the planned moments, and the sounds alone (shown +12 dB).

The first measurement found the sounds buried (whoosh-outs and typing at or under the floor): the
ducking took about 19 dB off under speech. It now takes about 5 dB, and the whooshes were made
louder (recipe version 3).

NOT VERIFIED: listening. Nobody heard these here; only their levels and timing were measured.
