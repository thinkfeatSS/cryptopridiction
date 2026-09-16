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
