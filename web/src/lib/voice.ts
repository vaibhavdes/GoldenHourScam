// Mic capture (16 kHz PCM16) -> WebSocket -> Gemini Live (via our proxy) -> 24 kHz PCM playback.
import { liveUrl } from "./api";

export type VoiceEvent =
  | { type: "transcript"; role: "user" | "model"; text: string }
  | { type: "tool"; name: string; result: unknown }
  | { type: "turn_complete" }
  | { type: "error"; message: string }
  | { type: "state"; state: "connecting" | "live" | "closed" };

function b64(buf: ArrayBuffer): string {
  let s = "";
  const bytes = new Uint8Array(buf);
  for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return btoa(s);
}

export class VoiceSession {
  private ws?: WebSocket;
  private ctxIn?: AudioContext;
  private ctxOut?: AudioContext;
  private stream?: MediaStream;
  private playAt = 0;
  private stopped = false;
  private rejectConnect?: (error: Error) => void;
  private connectTimer?: ReturnType<typeof setTimeout>;

  constructor(private caseId: string, private lang: string, private onEvent: (e: VoiceEvent) => void) {}

  async start(microphone = true) {
    try {
    this.onEvent({ type: "state", state: "connecting" });
    this.stopped = false;
    let node: AudioWorkletNode | undefined;
    if (microphone) {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });
    if (this.stopped) { stream.getTracks().forEach(track => track.stop()); return; }
    this.stream = stream;
    this.ctxIn = new AudioContext();
    await this.ctxIn.audioWorklet.addModule("/pcm-recorder.js");
    if (this.stopped || !this.ctxIn) return;
    const src = this.ctxIn.createMediaStreamSource(this.stream);
    node = new AudioWorkletNode(this.ctxIn, "pcm-recorder");
    src.connect(node);
    }
    this.ctxOut = new AudioContext({ sampleRate: 24000 });
    await this.ctxOut.resume();
    if (this.stopped) return;

    this.ws = new WebSocket(liveUrl(this.caseId, this.lang));
    const connected = new Promise<void>((resolve, reject) => {
      this.rejectConnect = reject;
      this.ws!.onopen = () => { clearTimeout(this.connectTimer); this.rejectConnect = undefined; this.onEvent({ type: "state", state: "live" }); resolve(); };
    });
    this.connectTimer = setTimeout(() => { this.onEvent({ type: "error", message: "Voice connection timed out. Use the checklist and call guidance." }); this.stop(); }, 15000);
    this.ws.onclose = () => this.stop();
    this.ws.onerror = () => {
      this.onEvent({ type: "error", message: this.lang === "hi" ? "आवाज़ का कनेक्शन नहीं हुआ" : "Voice connection failed" });
      this.stop();
    };
    this.ws.onmessage = (m) => {
      const msg = JSON.parse(m.data);
      if (msg.type === "audio") this.play(msg.data);
      else this.onEvent(msg);
    };
    if (node) node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
      if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "audio", data: b64(e.data) }));
    };
    await connected;
    } catch (error) {
      this.stop();
      throw error;
    }
  }

  sendText(text: string) {
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify({ type: "text", text }));
  }

  private play(data: string) {
    if (!this.ctxOut) return;
    const raw = atob(data);
    const pcm = new Int16Array(raw.length / 2);
    for (let i = 0; i < pcm.length; i++) {
      const lo = raw.charCodeAt(i * 2);
      const hi = raw.charCodeAt(i * 2 + 1);
      let v = (hi << 8) | lo;
      if (v >= 0x8000) v -= 0x10000;
      pcm[i] = v;
    }
    const buf = this.ctxOut.createBuffer(1, pcm.length, 24000);
    const ch = buf.getChannelData(0);
    for (let i = 0; i < pcm.length; i++) ch[i] = pcm[i] / 0x8000;
    const src = this.ctxOut.createBufferSource();
    src.buffer = buf;
    src.connect(this.ctxOut.destination);
    const now = this.ctxOut.currentTime;
    this.playAt = Math.max(this.playAt, now);
    src.start(this.playAt);
    this.playAt += buf.duration;
  }

  stop() {
    this.stopped = true;
    clearTimeout(this.connectTimer);
    this.rejectConnect?.(new Error("Voice connection stopped"));
    this.rejectConnect = undefined;
    const ws = this.ws;
    this.ws = undefined;
    try {
      if (ws?.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "end" }));
    } catch {
      /* ignore */
    }
    if (ws) { ws.onclose = null; ws.onerror = null; ws.onmessage = null; ws.close(); }
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = undefined;
    void this.ctxIn?.close().catch(() => {});
    void this.ctxOut?.close().catch(() => {});
    this.ctxIn = undefined;
    this.ctxOut = undefined;
    this.playAt = 0;
    this.onEvent({ type: "state", state: "closed" });
  }
}
