// "Fix my captions": the words Whisper heard, line by line, to correct before the AI edit.
// A line with the same number of words keeps their timing; otherwise the words share the line.
import { useState } from "react";
import { retimeLine, transcriptLines, type TranscriptWord } from "../../shared/captionEdit";
import { Dialog } from "./Dialogs";

export function TranscriptDialog({ words, onCancel, onDone }: {
  words: TranscriptWord[];
  onCancel: () => void;
  onDone: (words: TranscriptWord[]) => void;
}) {
  const lines = transcriptLines(words);
  const [texts, setTexts] = useState(lines.map((l) => l.map((w) => w.text).join(" ")));
  const done = () => onDone(lines.flatMap((line, i) => retimeLine(line, texts[i])));
  return (
    <Dialog title="Fix the words · Ayusin ang mga salita" onClose={onCancel}>
      <div className="stack" data-testid="transcript-fix">
        <p className="muted small" style={{ margin: 0 }}>
          This is what was heard. Correct any word (e.g. “Tatyo” → “Tatlo”), then press Edit. The captions
          and graphics use these words. · Itama ang mali, tapos pindutin ang Edit.
        </p>
        <div className="stack" style={{ maxHeight: "50vh", overflow: "auto" }}>
          {lines.map((line, i) => (
            <label key={i} className="field">
              <span className="muted small">{line[0].start.toFixed(1)} s</span>
              <input
                type="text"
                value={texts[i]}
                aria-label={`Line ${i + 1}`}
                onChange={(e) => setTexts((t) => t.map((x, k) => (k === i ? e.target.value : x)))}
              />
            </label>
          ))}
        </div>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn small ghost" onClick={onCancel}>Cancel</button>
          <button className="btn small primary" data-testid="transcript-done" onClick={done}>Edit with these words</button>
        </div>
      </div>
    </Dialog>
  );
}
