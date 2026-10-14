#include "audio.h"

#if defined(PBL_PLATFORM_EMERY)

#include "voices.h"

// Two channels (voice + sound effect) decoded from IMA ADPCM in the
// resources/voices.bin bank (tools/convert_audio.py), mixed, and streamed as
// 16 kHz 16-bit PCM. The stream is only open while something is playing.

#define AUDIO_TICK_MS 20
#define BLOCK_SAMPLES 256
#define MAX_BLOCKS_PER_PUMP 32
#define NUM_CH 2
#define LINGER_BLOCKS 94   // ~1.5 s of silence before the stream closes

// log what the speaker does (pebble logs --phone ...)
#define AUDIO_DEBUG 0
#if AUDIO_DEBUG
#define ALOG(...) APP_LOG(APP_LOG_LEVEL_INFO, __VA_ARGS__)
#else
#define ALOG(...)
#endif

static const int16_t STEP_TABLE[89] = {
  7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
  34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143,
  157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658,
  724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024,
  3327, 3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899,
  15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
};
static const int8_t INDEX_TABLE[16] = {
  -1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8,
};

typedef struct {
  bool active;
  uint32_t offset;     // next byte in the bank
  uint32_t remaining;  // samples left
  int32_t predictor;
  int step_index;
} Channel;

static Channel s_ch[NUM_CH];
static ResHandle s_res;
static bool s_open;
static uint8_t s_volume = 70;
static bool s_fed;   // the open stream has been given data
static int s_silent; // silent blocks fed since the last clip ended
#if AUDIO_DEBUG
static uint32_t s_dbg_written, s_dbg_full_at, s_dbg_max_gap, s_dbg_last;
static uint32_t dbg_ms(void) {
  time_t t; uint16_t ms; time_ms(&t, &ms);
  return (uint32_t)t * 1000 + ms;
}
static void finished(SpeakerFinishReason reason, void *ctx) {
  ALOG("spk finished reason=%d written=%lu", (int)reason, (unsigned long)s_dbg_written);
}
#endif
static AppTimer *s_timer;

static int16_t s_pcm[BLOCK_SAMPLES];
static uint32_t s_pcm_len;   // bytes
static uint32_t s_pcm_pos;   // bytes written so far

static inline int16_t decode_nibble(Channel *c, uint8_t nib) {
  int step = STEP_TABLE[c->step_index];
  int diff = step >> 3;
  if (nib & 4) diff += step;
  if (nib & 2) diff += step >> 1;
  if (nib & 1) diff += step >> 2;
  c->predictor += (nib & 8) ? -diff : diff;
  if (c->predictor > 32767) c->predictor = 32767;
  if (c->predictor < -32768) c->predictor = -32768;
  c->step_index += INDEX_TABLE[nib];
  if (c->step_index < 0) c->step_index = 0;
  if (c->step_index > 88) c->step_index = 88;
  return (int16_t)c->predictor;
}

// mix the next block of every active channel into s_pcm; false when silent
static bool mix_block(void) {
  static int32_t acc[BLOCK_SAMPLES];
  static uint8_t buf[BLOCK_SAMPLES / 2];
  bool any = false;
  memset(acc, 0, sizeof(acc));
  for (int i = 0; i < NUM_CH; i++) {
    Channel *c = &s_ch[i];
    if (!c->active) continue;
    uint32_t n = c->remaining < BLOCK_SAMPLES ? c->remaining : BLOCK_SAMPLES;
    uint32_t bytes = (n + 1) / 2;
    resource_load_byte_range(s_res, c->offset, buf, bytes);
    c->offset += bytes;
    for (uint32_t k = 0; k < n; k++) {
      uint8_t b = buf[k / 2];
      acc[k] += decode_nibble(c, (k & 1) ? (b >> 4) : (b & 0x0F));
    }
    c->remaining -= n;
    if (c->remaining == 0) c->active = false;
    any = true;
  }
  if (any) {
    s_silent = 0;
  } else {
    // keep the stream alive a little, so a clip that follows soon doesn't
    // have to reopen it (and cut off what is still buffered)
    if (++s_silent > LINGER_BLOCKS) return false;
    memset(s_pcm, 0, sizeof(s_pcm));
    s_pcm_len = sizeof(s_pcm);
    s_pcm_pos = 0;
    return true;
  }
  for (int k = 0; k < BLOCK_SAMPLES; k++) {
    int32_t v = acc[k];
    s_pcm[k] = v > 32767 ? 32767 : v < -32768 ? -32768 : (int16_t)v;
  }
  s_pcm_len = sizeof(s_pcm);
  s_pcm_pos = 0;
  return true;
}

static void tick(void *data);

// The firmware buffer is small, so it gets topped up as full as it will go
// on every call: from the timer, and from the renderer between chunks of
// work, because a heavy frame would otherwise let it run dry and cut the
// clip off.
void audio_pump(void) {
  if (!s_open) return;
#if AUDIO_DEBUG
  uint32_t now = dbg_ms();
  if (s_dbg_last && now - s_dbg_last > s_dbg_max_gap) s_dbg_max_gap = now - s_dbg_last;
  s_dbg_last = now;
  static uint32_t s_dbg_open_ms, s_dbg_next;
  if (!s_dbg_open_ms || s_dbg_written == 0) s_dbg_open_ms = now, s_dbg_next = now + 500;
  if (now >= s_dbg_next) {
    s_dbg_next = now + 500;
    ALOG("spk t=%lu ms accepted=%lu ms", (unsigned long)(now - s_dbg_open_ms),
         (unsigned long)(s_dbg_written / 32));
  }
#endif
  if (s_fed && speaker_get_status() == SpeakerStatusIdle) {
    ALOG("spk went idle while playing, written=%lu maxgap=%lu", (unsigned long)s_dbg_written,
         (unsigned long)s_dbg_max_gap);
    // the stream died (ran dry, or was preempted): start a fresh one
    s_fed = false;
    s_open = speaker_stream_open(SpeakerPcmFormat_16kHz_16bit, s_volume);
    if (!s_open) {
      APP_LOG(APP_LOG_LEVEL_WARNING, "speaker stream reopen failed");
      for (int i = 0; i < NUM_CH; i++) s_ch[i].active = false;
      return;
    }
  }
  for (int blocks = 0; blocks < MAX_BLOCKS_PER_PUMP; blocks++) {
    if (s_pcm_pos >= s_pcm_len && !mix_block()) {
      // nothing left: let the buffered audio drain and close
      ALOG("spk close written=%lu buf=%lu maxgap=%lu status=%d", (unsigned long)s_dbg_written,
           (unsigned long)s_dbg_full_at, (unsigned long)s_dbg_max_gap, (int)speaker_get_status());
      speaker_stream_close();
      s_open = false;
      return;
    }
    uint32_t n = speaker_stream_write((const uint8_t *)s_pcm + s_pcm_pos,
                                      s_pcm_len - s_pcm_pos);
    if (n) s_fed = true;
#if AUDIO_DEBUG
    s_dbg_written += n;
    if (n < s_pcm_len - s_pcm_pos && !s_dbg_full_at) s_dbg_full_at = s_dbg_written;
#endif
    s_pcm_pos += n;
    if (s_pcm_pos < s_pcm_len) break;  // stream buffer full
  }
}

static void tick(void *data) {
  s_timer = NULL;
  audio_pump();
  if (s_open) s_timer = app_timer_register(AUDIO_TICK_MS, tick, NULL);
}

void audio_play(int channel, int id) {
  ALOG("play ch=%d id=%d muted=%d status=%d open=%d", channel, id, (int)speaker_is_muted(),
       (int)speaker_get_status(), (int)s_open);
  if (channel < 0 || channel >= NUM_CH || s_volume == 0 || speaker_is_muted()) return;
  s_res = resource_get_handle(RESOURCE_ID_VOICES);
  uint16_t count;
  resource_load_byte_range(s_res, 0, (uint8_t *)&count, 2);
  if (id < 0 || id >= count) return;
  uint32_t entry[2];
  resource_load_byte_range(s_res, 4 + id * 8, (uint8_t *)entry, 8);

  Channel *c = &s_ch[channel];
  c->offset = entry[0];
  c->remaining = entry[1];
  c->predictor = 0;
  c->step_index = 0;
  c->active = true;

  if (!s_open) {
    // an earlier stream may still be draining its tail; open would fail
    if (speaker_get_status() != SpeakerStatusIdle) speaker_stop();
#if AUDIO_DEBUG
    speaker_set_finish_callback(finished, NULL);
    s_dbg_written = s_dbg_full_at = s_dbg_max_gap = s_dbg_last = 0;
#endif
    s_open = speaker_stream_open(SpeakerPcmFormat_16kHz_16bit, s_volume);
    ALOG("spk open -> %d", (int)s_open);
    if (!s_open) {
      APP_LOG(APP_LOG_LEVEL_WARNING, "speaker stream open failed");
      c->active = false;
      return;
    }
    s_fed = false;
    s_silent = 0;
    s_pcm_len = s_pcm_pos = 0;
  }
  audio_pump();
  if (s_open && !s_timer) s_timer = app_timer_register(AUDIO_TICK_MS, tick, NULL);
}

void audio_set_volume(int volume) {
  s_volume = volume;
  if (s_open) {
    if (volume == 0) audio_deinit();
    else speaker_set_volume(volume);
  }
}

bool audio_busy(void) {
  return s_open;
}

void audio_play_random(int channel, int first, int count) {
  audio_play(channel, first + rand() % count);
}

void audio_deinit(void) {
  if (s_timer) app_timer_cancel(s_timer);
  s_timer = NULL;
  if (s_open) speaker_stop();
  s_open = false;
}

#else

void audio_play(int channel, int id) {}
void audio_play_random(int channel, int first, int count) {}
void audio_pump(void) {}
bool audio_busy(void) { return false; }
void audio_set_volume(int volume) {}
void audio_deinit(void) {}

#endif
