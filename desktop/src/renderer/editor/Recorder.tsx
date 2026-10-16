// Record a voice-over in the app: pick a microphone, watch the level, 3-2-1, record, listen,
// then it goes on the Voice-over track at the playhead.
import { useEffect, useRef, useState } from "react";
import { Dialog } from "../components/Dialogs";

type Phase = "idle" | "countdown" | "recording" | "done";

export function pickMimeType(isSupported: (t: string) => boolean): { mime: string; extension: string } {
  for (const [mime, extension] of [
    ["audio/webm;codecs=opus", "webm"],
    ["audio/webm", "webm"],
    ["audio/ogg;codecs=opus", "ogg"],
  ] as const) {
    if (isSupported(mime)) return { mime, extension };
  }
  return { mime: "", extension: "webm" };
}

export function Recorder({ startAt, onUse, onClose }: { startAt: string; onUse: (data: Uint8Array, extension: string) => Promise<void>; onClose: () => void }) {
  const [mics, setMics] = useState<MediaDeviceInfo[]>([]);
  /** The microphone you picked ("" = the system's default); `active` is the one in use. */
  const [mic, setMic] = useState("");
  const [active, setActive] = useState("");
  const [level, setLevel] = useState(0);
  const [phase, setPhase] = useState<Phase>("idle");
  const [count, setCount] = useState(3);
  const [seconds, setSeconds] = useState(0);
  const [clip, setClip] = useState<{ url: string; blob: Blob; extension: string } | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const stream = useRef<MediaStream | null>(null);
  const recorder = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);
  const timers = useRef<number[]>([]);

  // Open the microphone (for the level meter), and list the microphones.
  useEffect(() => {
    let raf = 0;
    let ctx: AudioContext | null = null;
    let cancelled = false;
    (async () => {
      try {
        const s = await navigator.mediaDevices.getUserMedia({ audio: mic ? { deviceId: { exact: mic } } : true });
        if (cancelled) return s.getTracks().forEach((t) => t.stop());
        stream.current = s;
        const devices = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "audioinput");
        setMics(devices);
        setActive(s.getAudioTracks()[0]?.getSettings().deviceId ?? devices[0]?.deviceId ?? "");
        ctx = new AudioContext();
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 1024;
        ctx.createMediaStreamSource(s).connect(analyser);
        const buf = new Float32Array(analyser.fftSize);
        let shown = 0;
        const tick = () => {
          analyser.getFloatTimeDomainData(buf);
          let peak = 0;
          for (const v of buf) peak = Math.max(peak, Math.abs(v));
          // Like a real level meter: jump up at once, fall back slowly (easier to read).
          shown = Math.max(peak, shown * 0.94);
          setLevel(shown);
          raf = requestAnimationFrame(tick);
        };
        tick();
        setError("");
      } catch (err) {
        setError(`The microphone could not be opened: ${(err as Error).message}. Check that a microphone is connected and that Windows lets apps use it (Settings → Privacy → Microphone).`);
      }
    })();
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      void ctx?.close();
      stream.current?.getTracks().forEach((t) => t.stop());
    };
  }, [mic]);

  useEffect(() => () => timers.current.forEach((t) => clearTimeout(t)), []);

  const start = () => {
    if (!stream.current) return;
    setClip(null);
    setPhase("countdown");
    setCount(3);
    for (let i = 1; i <= 3; i++) {
      timers.current.push(window.setTimeout(() => {
        if (i < 3) setCount(3 - i);
        else record();
      }, i * 1000));
    }
  };

  const record = () => {
    const { mime, extension } = pickMimeType((t) => MediaRecorder.isTypeSupported(t));
    const r = new MediaRecorder(stream.current!, mime ? { mimeType: mime } : undefined);
    chunks.current = [];
    r.ondataavailable = (e) => e.data.size && chunks.current.push(e.data);
    r.onstop = () => {
      const blob = new Blob(chunks.current, { type: mime || "audio/webm" });
      setClip({ url: URL.createObjectURL(blob), blob, extension });
      setPhase("done");
    };
    recorder.current = r;
    r.start(250);
    setPhase("recording");
    setSeconds(0);
    const began = Date.now();
    const tick = () => {
      if (recorder.current?.state !== "recording") return;
      setSeconds((Date.now() - began) / 1000);
      timers.current.push(window.setTimeout(tick, 200));
    };
    tick();
  };

  const stop = () => recorder.current?.state === "recording" && recorder.current.stop();

  const use = async () => {
    if (!clip) return;
    setSaving(true);
    try {
      await onUse(new Uint8Array(await clip.blob.arrayBuffer()), clip.extension);
    } finally {
      setSaving(false);
    }
  };

  const loud = level > 0.95;
  return (
    <Dialog title="Record a voice-over · Mag-record ng boses" onClose={phase === "recording" || phase === "countdown" ? undefined : onClose}>
      <div className="stack" data-testid="recorder">
        <div className="field">
          <label htmlFor="mic">Microphone</label>
          <select id="mic" value={mic || active} onChange={(e) => setMic(e.target.value)} disabled={phase === "recording" || phase === "countdown"}>
            {mics.map((m, i) => (
              <option key={m.deviceId || i} value={m.deviceId}>{m.label || `Microphone ${i + 1}`}</option>
            ))}
          </select>
        </div>
        <div className="meter" aria-label="Microphone level" role="meter" aria-valuenow={Math.round(level * 100)} aria-valuemin={0} aria-valuemax={100} data-testid="meter">
          <div className={loud ? "loud" : ""} style={{ width: `${Math.min(100, level * 100)}%` }} />
        </div>
        <p className="muted small" style={{ margin: 0 }}>
          {loud ? "Too loud: move back a little from the microphone." : `Speak normally; the bar should move. It starts at the playhead (${startAt}).`}
        </p>
        {phase === "countdown" && <div className="countdown" aria-live="assertive" data-testid="countdown">{count}</div>}
        {phase === "recording" && (
          <p className="recording" aria-live="polite" data-testid="recording">● Recording… {seconds.toFixed(1)} s</p>
        )}
        {clip && <audio controls src={clip.url} data-testid="take" style={{ width: "100%" }} />}
        {error && <p className="error" role="alert">{error}</p>}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          {phase === "recording" ? (
            <button className="btn danger" onClick={stop}>■ Stop</button>
          ) : (
            <>
              <button className="btn" onClick={onClose} disabled={phase === "countdown"}>Cancel</button>
              <button className="btn" onClick={start} disabled={!stream.current || phase === "countdown"}>{clip ? "Record again" : "● Record"}</button>
              {clip && (
                <button className="btn primary" onClick={use} disabled={saving} data-testid="use-take">{saving ? "Adding…" : "Use it"}</button>
              )}
            </>
          )}
        </div>
      </div>
    </Dialog>
  );
}
