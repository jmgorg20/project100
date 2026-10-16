// Your words and corrections for Taglish transcripts. Saved in vocabulary.json and used for
// every transcription (the words as a hint, the corrections applied after).
import { useEffect, useState } from "react";
import { cleanVocabulary, type Correction, type Vocabulary } from "../../shared/captionEdit";
import { Dialog } from "../components/Dialogs";
import { api } from "../lib/api";

export function VocabularyDialog({ onClose, onApply }: { onClose: () => void; onApply: (corrections: Correction[]) => void }) {
  const [vocab, setVocab] = useState<Vocabulary | null>(null);
  const [word, setWord] = useState("");
  const [status, setStatus] = useState("");

  useEffect(() => {
    api.getVocabulary().then((v) => setVocab({ ...v, corrections: [...v.corrections, { from: "", to: "" }] }));
  }, []);

  if (!vocab) return null;
  const setFix = (i: number, patch: Partial<Correction>) =>
    setVocab((v) => {
      const corrections = v!.corrections.map((c, k) => (k === i ? { ...c, ...patch } : c));
      const last = corrections[corrections.length - 1];
      if (last.from || last.to) corrections.push({ from: "", to: "" }); // always one empty row
      return { ...v!, corrections };
    });
  const addWord = () => {
    if (!word.trim()) return;
    setVocab((v) => ({ ...v!, words: [...v!.words, ...word.split(",").map((w) => w.trim()).filter(Boolean)] }));
    setWord("");
  };
  const save = async () => {
    const clean = cleanVocabulary(vocab);
    const r = await api.setVocabulary(clean);
    setStatus(r.ok ? "Saved. New transcripts will use it. · Naka-save." : r.error ?? "Could not save.");
    return r.ok ? clean : null;
  };

  return (
    <Dialog title="Your words & corrections" onClose={onClose}>
      <div className="stack" data-testid="vocabulary">
        <p className="muted small" style={{ margin: 0 }}>
          Names and words the transcriber should spell right (brands, people, places, slang), and fixes for what it still gets wrong.
          Ilagay ang mga salitang madalas mong gamitin.
        </p>
        <div className="field">
          <label htmlFor="vocab-word">Words</label>
          <div className="chips">
            {vocab.words.map((w, i) => (
              <span className="chip" key={`${w}-${i}`}>
                <span>{w}</span>
                <button aria-label={`Remove ${w}`} onClick={() => setVocab((v) => ({ ...v!, words: v!.words.filter((_, k) => k !== i) }))}>×</button>
              </span>
            ))}
          </div>
          <div className="row">
            <input id="vocab-word" type="text" value={word} placeholder="e.g. GCash, Shopee, Ate Rose" onChange={(e) => setWord(e.target.value)} onKeyDown={(e) => e.key === "Enter" && addWord()} />
            <button className="btn small" onClick={addWord}>Add</button>
          </div>
        </div>
        <div className="field">
          <label>Corrections: when it hears… → write…</label>
          <table className="fix-table">
            <tbody>
              {vocab.corrections.map((c, i) => (
                <tr key={i}>
                  <td><input type="text" value={c.from} placeholder="g cash" aria-label={`Wrong ${i + 1}`} onChange={(e) => setFix(i, { from: e.target.value })} /></td>
                  <td aria-hidden="true">→</td>
                  <td><input type="text" value={c.to} placeholder="GCash" aria-label={`Right ${i + 1}`} onChange={(e) => setFix(i, { to: e.target.value })} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {status && <p className="small" role="status">{status}</p>}
        <div className="row" style={{ justifyContent: "flex-end", flexWrap: "wrap" }}>
          <button className="btn" onClick={onClose}>Close</button>
          <button className="btn" onClick={async () => { const v = await save(); if (v) onApply(v.corrections); }} data-testid="vocab-apply">
            Save & fix this video's captions
          </button>
          <button className="btn primary" onClick={save} data-testid="vocab-save">Save</button>
        </div>
      </div>
    </Dialog>
  );
}
