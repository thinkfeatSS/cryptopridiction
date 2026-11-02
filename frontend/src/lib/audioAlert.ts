/**
 * Web Audio API Synthesizer for Real-Time Crypto Signal Audio Alerts & Beeps
 * Zero external audio file dependencies - Works smoothly across modern browsers.
 */

let audioCtx: AudioContext | null = null;

function getAudioContext(): AudioContext | null {
  if (typeof window === "undefined") return null;
  try {
    if (!audioCtx) {
      const AudioContextClass = window.AudioContext || (window as any).webkitAudioContext;
      if (AudioContextClass) {
        audioCtx = new AudioContextClass();
      }
    }
    if (audioCtx && audioCtx.state === "suspended") {
      audioCtx.resume();
    }
    return audioCtx;
  } catch (e) {
    console.warn("AudioContext not supported or blocked:", e);
    return null;
  }
}

/**
 * Plays a crisp, professional dual-frequency high-edge buy chime (880Hz -> 1318Hz)
 */
export function playSignalChime(volume: number = 0.3) {
  const ctx = getAudioContext();
  if (!ctx) return;

  try {
    const now = ctx.currentTime;

    // Tone 1: 880Hz (A5)
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = "sine";
    osc1.frequency.setValueAtTime(880, now);
    gain1.gain.setValueAtTime(volume, now);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.12);
    osc1.connect(gain1);
    gain1.connect(ctx.destination);
    osc1.start(now);
    osc1.stop(now + 0.12);

    // Tone 2: 1318.5Hz (E6) - High harmonic confirmation
    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = "sine";
    osc2.frequency.setValueAtTime(1318.5, now + 0.08);
    gain2.gain.setValueAtTime(volume * 1.2, now + 0.08);
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.28);
    osc2.connect(gain2);
    gain2.connect(ctx.destination);
    osc2.start(now + 0.08);
    osc2.stop(now + 0.28);
  } catch (e) {
    console.warn("Audio chime playback error:", e);
  }
}

/**
 * Plays an urgent parabolic volatility breakout pulse (Tri-Tone Arpeggio)
 */
export function playParabolicBreakoutAlert(volume: number = 0.35) {
  const ctx = getAudioContext();
  if (!ctx) return;

  try {
    const now = ctx.currentTime;
    const notes = [659.25, 880.0, 1174.66, 1760.0]; // E5 -> A5 -> D6 -> A6
    notes.forEach((freq, idx) => {
      const startTime = now + (idx * 0.07);
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(freq, startTime);
      gain.gain.setValueAtTime(volume, startTime);
      gain.gain.exponentialRampToValueAtTime(0.001, startTime + 0.15);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(startTime);
      osc.stop(startTime + 0.15);
    });
  } catch (e) {
    console.warn("Breakout alert playback error:", e);
  }
}

/**
 * Plays a distinct high-urgency descending exhaustion chime (E6 -> B5 -> G5 -> D5)
 * Warning traders that momentum has topped and market is reversing downward.
 */
export function playExhaustionSellAlert(volume: number = 0.38) {
  const ctx = getAudioContext();
  if (!ctx) return;

  try {
    const now = ctx.currentTime;
    const notes = [1318.5, 987.77, 783.99, 587.33]; // Descending E6 -> B5 -> G5 -> D5
    notes.forEach((freq, idx) => {
      const startTime = now + (idx * 0.08);
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sawtooth"; // Distinctive warning timbre
      osc.frequency.setValueAtTime(freq, startTime);
      gain.gain.setValueAtTime(volume, startTime);
      gain.gain.exponentialRampToValueAtTime(0.001, startTime + 0.18);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(startTime);
      osc.stop(startTime + 0.18);
    });
  } catch (e) {
    console.warn("Exhaustion sell alert playback error:", e);
  }
}

/**
 * Plays a triumphant ascending 3-tone victory fanfare on TP Hits (+Profit Win)
 */
export function playTpHitChime(volume: number = 0.35) {
  const ctx = getAudioContext();
  if (!ctx) return;

  try {
    const now = ctx.currentTime;
    // C6 (1046.5Hz) -> E6 (1318.5Hz) -> G6 (1567.98Hz) -> C7 (2093.0Hz)
    const notes = [1046.5, 1318.5, 1567.98, 2093.0];
    notes.forEach((freq, idx) => {
      const startTime = now + idx * 0.07;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, startTime);
      gain.gain.setValueAtTime(volume * (1 + idx * 0.15), startTime);
      gain.gain.exponentialRampToValueAtTime(0.001, startTime + 0.22);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(startTime);
      osc.stop(startTime + 0.22);
    });
  } catch (e) {
    console.warn("TP hit chime error:", e);
  }
}

/**
 * Plays a protective low warning tone on Stop-Loss Hits
 */
export function playSlHitChime(volume: number = 0.30) {
  const ctx = getAudioContext();
  if (!ctx) return;

  try {
    const now = ctx.currentTime;
    // Descending minor interval: 440Hz (A4) -> 370Hz (F#4) -> 311.13Hz (Eb4)
    const notes = [440.0, 370.0, 311.13];
    notes.forEach((freq, idx) => {
      const startTime = now + idx * 0.09;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "triangle";
      osc.frequency.setValueAtTime(freq, startTime);
      gain.gain.setValueAtTime(volume, startTime);
      gain.gain.exponentialRampToValueAtTime(0.001, startTime + 0.25);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(startTime);
      osc.stop(startTime + 0.25);
    });
  } catch (e) {
    console.warn("SL hit chime error:", e);
  }
}

/**
 * Plays a clean harmonic confirmation tone on Breakeven Protection lock
 */
export function playBreakEvenChime(volume: number = 0.28) {
  const ctx = getAudioContext();
  if (!ctx) return;

  try {
    const now = ctx.currentTime;
    // Dual fifth harmony: 587.33Hz (D5) -> 880Hz (A5)
    [587.33, 880.0].forEach((freq, idx) => {
      const startTime = now + idx * 0.06;
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.setValueAtTime(freq, startTime);
      gain.gain.setValueAtTime(volume, startTime);
      gain.gain.exponentialRampToValueAtTime(0.001, startTime + 0.18);
      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(startTime);
      osc.stop(startTime + 0.18);
    });
  } catch (e) {
    console.warn("Breakeven chime error:", e);
  }
}

/**
 * Plays a subtle neutral ping when a trade expires
 */
export function playExpiredChime(volume: number = 0.22) {
  const ctx = getAudioContext();
  if (!ctx) return;

  try {
    const now = ctx.currentTime;
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = "sine";
    osc.frequency.setValueAtTime(740.0, now);
    gain.gain.setValueAtTime(volume, now);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.15);
    osc.connect(gain);
    gain.connect(ctx.destination);
    osc.start(now);
    osc.stop(now + 0.15);
  } catch (e) {
    console.warn("Expired chime error:", e);
  }
}

