import io
import math
import random
import struct
import wave

SAMPLE_RATE = 44100


def samples_to_wav_bytes(samples):
  buf = io.BytesIO()
  with wave.open(buf, "wb") as wf:
    wf.setnchannels(1)
    wf.setsampwidth(2)
    wf.setframerate(SAMPLE_RATE)
    clamped = [max(-32767, min(32767, int(s))) for s in samples]
    wf.writeframes(struct.pack(f"<{len(clamped)}h", *clamped))
  return buf.getvalue()


def wav_bytes_to_samples(wav_bytes):
  buf = io.BytesIO(wav_bytes)
  with wave.open(buf, "rb") as wf:
    n = wf.getnframes()
    return list(struct.unpack(f"<{n}h", wf.readframes(n)))


def stretch_samples(samples, factor):
  new_len = int(len(samples) * factor)
  if new_len < 2:
    return samples
  out, max_idx = [], len(samples) - 1
  for i in range(new_len):
    pos = i / factor
    idx = int(pos)
    frac = pos - idx
    if idx >= max_idx:
      out.append(samples[max_idx])
    else:
      out.append(int(samples[idx] * (1 - frac) + samples[idx + 1] * frac))
  return out


def gen_synth_arp():
  notes = [261.63, 329.63, 392.00, 493.88]
  s = []
  for _ in range(3):
    for f in notes:
      n = int(SAMPLE_RATE * 0.25)
      for i in range(n):
        t = i / SAMPLE_RATE
        val = 2.0 * (t * f - math.floor(0.5 + t * f))
        s.append(int(val * min(1.0, i / 400, (n - i) / 400) * 16000))
  return samples_to_wav_bytes(s)


def gen_bass_line():
  s = []
  for f in [65.41, 65.41, 82.41, 98.00]:
    n = int(SAMPLE_RATE * 0.75)
    for i in range(n):
      t = i / SAMPLE_RATE
      val = math.sin(2 * math.pi * f * t) + 0.3 * math.sin(4 * math.pi * f * t)
      s.append(int(val * min(1.0, i / 600, (n - i) / 1000) * 18000))
  return samples_to_wav_bytes(s)


def gen_electric_piano():
  chords = [
      [261.63, 329.63, 392.00, 493.88],
      [220.00, 261.63, 329.63, 392.00],
  ]
  s = []
  for chord in chords:
    n = int(SAMPLE_RATE * 1.5)
    for i in range(n):
      t = i / SAMPLE_RATE
      val = sum(
          math.sin(
              2 * math.pi * f * t
              + 0.6 * math.sin(4 * math.pi * f * t) * math.exp(-t * 6)
          )
          for f in chord
      )
      s.append(
          int((val / len(chord)) * min(1.0, i / 800) * math.exp(-t * 1.4) * 20000)
      )
  return samples_to_wav_bytes(s)


def gen_lead_guitar():
  s = []
  for f in [523.25, 493.88, 392.00, 329.63, 392.00, 493.88]:
    n = int(SAMPLE_RATE * 0.5)
    d = max(2, int(SAMPLE_RATE / f))
    ring = [random.uniform(-1, 1) for _ in range(d)]
    idx = 0
    for i in range(n):
      cur = ring[idx]
      ring[idx] = 0.994 * 0.5 * (cur + ring[(idx + 1) % d])
      idx = (idx + 1) % d
      s.append(int(cur * min(1.0, i / 200, (n - i) / 500) * 18000))
  return samples_to_wav_bytes(s)


def gen_string_pad():
  freqs = [130.81, 196.00, 246.94, 329.63]
  n = int(SAMPLE_RATE * 3.0)
  s = []
  for i in range(n):
    t = i / SAMPLE_RATE
    val = sum(
        math.sin(2 * math.pi * f * t) + 0.7 * math.sin(2 * math.pi * f * 1.004 * t)
        for f in freqs
    )
    s.append(
        int((val / (len(freqs) * 1.7)) * math.sin(math.pi * (i / n)) * 16000)
    )
  return samples_to_wav_bytes(s)


def gen_snare_clap_beat():
  pat = [
      "kick",
      "hat",
      "snare",
      "hat",
      "kick",
      "kick",
      "snare",
      "hat",
      "kick",
      "hat",
      "snare",
      "hat",
  ]
  s = []
  for hit in pat:
    n = int(SAMPLE_RATE * 0.25)
    for i in range(n):
      t = i / SAMPLE_RATE
      if hit == "kick":
        val = math.sin(2 * math.pi * (42 + 110 * math.exp(-t * 28)) * t) * math.exp(
            -t * 12
        )
        s.append(int(val * 24000))
      elif hit == "snare":
        val = 0.4 * math.sin(360 * math.pi * t) * math.exp(
            -t * 20
        ) + 0.6 * random.uniform(-1, 1) * math.exp(-t * 16)
        s.append(int(val * 20000))
      else:
        s.append(int(random.uniform(-1, 1) * math.exp(-t * 50) * 9000))
  return samples_to_wav_bytes(s)


PRESETS = {
    "synth_arp": gen_synth_arp,
    "sub_bass": gen_bass_line,
    "electric_piano": gen_electric_piano,
    "lead_guitar": gen_lead_guitar,
    "string_pad": gen_string_pad,
    "snare_clap_beat": gen_snare_clap_beat,
}
def insert_at_timestamp(base_samples, clip_samples, insert_sec, mode="insert"):
  """Inserts (shifts audio forward) or overlays (mixes) clip_samples at insert_sec."""
  idx = max(0, min(len(base_samples), int(insert_sec * SAMPLE_RATE)))
  if mode == "insert":
    return base_samples[:idx] + clip_samples + base_samples[idx:]
  else:  # overlay / punch-in at timestamp
    end_len = max(len(base_samples), idx + len(clip_samples))
    out = list(base_samples) + [0] * (end_len - len(base_samples))
    for i, val in enumerate(clip_samples):
      out[idx + i] = int((out[idx + i] + val) * 0.75)
    return out
