#pragma once

#include <pebble.h>

// Turret voice lines and sound effects through the speaker (Time 2 only;
// every call is a no-op on watches without one).

#define AUDIO_CH_VOICE 0
#define AUDIO_CH_SFX 1

// Play clip `id` (see voices.h) on a channel, replacing whatever it played.
void audio_play(int channel, int id);

// Play a random clip from [first, first + count).
void audio_play_random(int channel, int first, int count);

// Top up the speaker buffer; cheap when nothing is playing. Call it between
// chunks of heavy work so playback doesn't stall.
void audio_pump(void);

// 0..100; 0 turns the sounds off
void audio_set_volume(int volume);

// true while the speaker stream is open
bool audio_busy(void);

void audio_deinit(void);
