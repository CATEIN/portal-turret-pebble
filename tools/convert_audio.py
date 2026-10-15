"""Pack the turret voice lines into one IMA ADPCM sound bank for the Time 2
(emery) speaker.

usage: convert_audio.py WAV_DIR resources/voices.bin resources/voices_lite.bin src/c/voices.h

Writes two banks: voices.bin with every clip (Portal Turret), and
voices_lite.bin with only the regular turret's (Portal Turret Lite, without
the defective turret). The regular clips come first, so their ids are the same in
both and one voices.h serves both.

WAV_DIR holds the clips from https://theportalwiki.com/wiki/Turret_voice_lines
(saved as e.g. turret_deploy_6.wav). Needs ffmpeg.

Bank layout (little-endian):
  u16 count, u16 pad
  count x { u32 byte offset, u32 sample count }
  ADPCM data, 16 kHz mono, 4 bits/sample, each clip starting from a reset
  decoder state (low nibble first).
"""
import os
import struct
import subprocess
import sys

import ima_adpcm

RATE = 16000

# (wav name, C name) -- order defines the clip ids
DEPLOY = [
    ('turret_deploy_6', 'WHOS_THERE'),
    ('turret_deploy_1', 'HELLO'),
    ('turret_deploy_5', 'THERE_YOU_ARE'),
    ('turret_active_2', 'TARGET_ACQUIRED'),
    ('turret_active_8', 'I_SEE_YOU'),
    ('turret_autosearch_5', 'IS_ANYONE_THERE'),
    ('turret_autosearch_4', 'SENTRY_MODE'),
    ('turret_deploy_2', 'DEPLOYING'),
    ('turret_deploy_4', 'ACTIVATED'),
    ('turret_active_1', 'HI'),
    ('turret_autosearch_1', 'HELLO_2'),
]
RETIRE = [
    ('turret_search_1', 'ARE_YOU_STILL_THERE'),
    ('turret_search_2', 'TARGET_LOST'),
    ('turret_retire_2', 'SLEEP_MODE'),
    ('turret_retire_4', 'HIBERNATING'),
    ('turret_retire_5', 'GOODNIGHT'),
    ('turret_retire_6', 'RESTING'),
    ('turret_retire_1', 'GOODBYE'),
    ('turret_retire_7', 'NAP_TIME'),
]
# knocked over: one of these as it falls...
TIPPED = [
    ('turret_tipped_4', 'MALFUNCTIONING'),
    ('turret_tipped_2', 'SELF_TEST_ERROR'),
    ('turret_tipped_6', 'OW_OW_OW'),
    ('turret_tipped_3', 'UNKNOWN_ERROR'),
    ('turret_tipped_1', 'AAH'),
    ('turret_tipped_5', 'AAAAH'),
    ('turret_pickup_9', 'HELP'),
]
# ...and one of these as it shuts down
DISABLED = [
    ('turret_disabled_2', 'CRITICAL_ERROR'),
    ('turret_disabled_4', 'SHUTTING_DOWN'),
    ('turret_disabled_5', 'I_DONT_BLAME_YOU'),
    ('turret_disabled_6', 'I_DONT_HATE_YOU'),
    ('turret_disabled_8', 'NO_HARD_FEELINGS'),
    ('turret_disabled_7', 'WHY'),
]
# spotting you: one of these, or Target acquired / I see you from DEPLOY
SPOTTED = [
    ('turret_active_6', 'GOTCHA'),
    ('turret_active_4', 'FIRING'),
    ('turret_active_7', 'THERE_YOU_ARE_2'),
    ('turret_suppress_1', 'HOLD_STILL'),
]
# after it gets you
KILLED = [
    ('turret_suppress_2', 'TARGET_SUPPRESSED'),
    ('turret_witnessdeath15', 'NOTED'),
    ('turret_witnessdeath09', 'OH_DEAR'),
]
# The defective turret (Portal 2) has its own lines: Defective_Turret_voice_lines
# on the Portal Wiki, saved as defect_<name>.wav (e.g. defect_prerange01.wav;
# glados_battle_defect_arrive08 as defect_arrive08, finale02_turret_return_defect_fail15
# as defect_return_fail15).
DEF_WAKE = [
    ('defect_prerange01', 'WATCH_AND_LEARN'),
    ('defect_prerange04', 'TIME_TO_WATCH_THE_MASTER'),
    ('defect_prerange07', 'IDENTIFY_YOURSELF'),
    ('defect_test08', 'PUT_ME_IN_THE_GAME'),
    ('defect_test17', 'IM_NOT_DEFECTIVE'),
    ('defect_test03', 'PLEASED_TO_MEETCHA'),
    ('defect_test11', 'MAKE_YOU_PROUD'),
    ('defect_arrive08', 'LOCKED_AND_LOADED'),
    ('defect_arrive01', 'MY_BIG_CHANCE'),
]
DEF_SPOTTED = [
    ('defect_prerange02', 'CHECK_THIS_OUT'),
    ('defect_prerange03', 'STAND_BACK_EVERYBODY'),
    ('defect_test05', 'LETS_DO_THIS'),
    ('defect_arrive06', 'YOU_ASKED_FOR_THIS'),
    ('defect_fail27', 'WRONG_TURRET'),
    ('defect_arrive19', 'DIE'),
]
DEF_NO_BULLETS = [
    ('defect_postrange09', 'NO_BULLETS_SORRY'),
    ('defect_postrange07', 'ANYONE_GOT_BULLETS'),
    ('defect_postrange17', 'DID_I_HIT_IT'),
    ('defect_postrange19', 'SHOOTIN_BLANKS'),
    ('defect_postrange02', 'BLAM_BLAM_BLAM'),
    ('defect_return_fail15', 'STILL_DEFECTIVE'),
    ('defect_return_fail14', 'STILL_BLIND'),
]
DEF_PANIC = [
    ('defect_fail02', 'NO_WAIT_WAIT'),
    ('defect_fail03', 'WHOA_WHOA_WHOA'),
    ('defect_fail11', 'YOU_CANT_FIRE_ME'),
    ('defect_fail13', 'JUST_PERFECT'),
    ('defect_fail19', 'NONONONO'),
    ('defect_fail06', 'WHAT_ARE_YOU_DOING'),
]
# burning, before it blows
DEF_ON_FIRE = [
    ('defect_arrive18', 'IM_ON_FIRE'),
    ('defect_arrive16', 'THIS_AINT_GOOD'),
]
DEF_GIVEUP = [
    ('defect_fail08', 'WELL_I_TRIED'),
    ('defect_fail09', 'CANT_WIN_EM_ALL'),
    ('defect_return_fail23', 'ALRIGHT_YOU_CAN_GO'),
    ('defect_return_fail28', 'WELL_PLAYED'),
]
DEF_RETIRE = [
    ('defect_postrange24', 'STANDING_DOWN'),
    ('defect_postrange23', 'HOW_WAS_THAT'),
    ('defect_postrange25', 'IM_TROUBLE'),
    ('defect_return_goodbye07', 'DONT_BE_A_STRANGER'),
    ('defect_return_goodbye08', 'BEEN_A_PLEASURE'),
]
SFX = [
    ('deploy', 'SFX_DEPLOY'),
    ('retract', 'SFX_RETRACT'),
    ('fire', 'SFX_FIRE'),       # turret_fire_4x_01: a burst of 4 shots
    ('die', 'SFX_DIE'),         # Turret_die
]
DEF_SFX = [
    ('defect_dryfire01', 'SFX_DRYFIRE'),  # clickclickclick: a defective turret firing
    ('explode', 'SFX_EXPLODE'),  # made by tools/make_explosion.py
    ('burn', 'SFX_BURN'),        # made by tools/make_fire.py
]
GROUPS = [('DEPLOY', DEPLOY), ('RETIRE', RETIRE), ('TIPPED', TIPPED), ('DISABLED', DISABLED),
          ('SPOTTED', SPOTTED), ('KILLED', KILLED), ('SFX', SFX)]
DEF_GROUPS = [('DEF_WAKE', DEF_WAKE), ('DEF_SPOTTED', DEF_SPOTTED),
              ('DEF_NO_BULLETS', DEF_NO_BULLETS), ('DEF_PANIC', DEF_PANIC), ('DEF_ON_FIRE', DEF_ON_FIRE),
              ('DEF_GIVEUP', DEF_GIVEUP), ('DEF_RETIRE', DEF_RETIRE), ('DEF_SFX', DEF_SFX)]
# clips cut short (seconds, with a fade-out) to save space
MAX_SECONDS = {'die': 1.3}


def load(path, trim, max_s=None):
    # mono 16 kHz, optional silence trim at both ends, peak-normalised
    filt = 'aresample=16000'
    if max_s:
        filt = f'atrim=0:{max_s},afade=t=out:st={max_s - 0.35}:d=0.35,' + filt
    if trim:
        filt = ('silenceremove=start_periods=1:start_threshold=-45dB,areverse,'
                'silenceremove=start_periods=1:start_threshold=-45dB,areverse,' + filt)
    raw = subprocess.run(['ffmpeg', '-v', 'error', '-i', path, '-af', filt, '-ac', '1',
                          '-f', 's16le', '-acodec', 'pcm_s16le', '-'],
                         check=True, capture_output=True).stdout
    s = list(struct.unpack('<%dh' % (len(raw) // 2), raw))
    peak = max(1, max(abs(x) for x in s))
    g = 30000 / peak
    return [int(x * g) for x in s]


def main():
    wav_dir, out_bin, out_lite, out_h = sys.argv[1:5]
    n_regular = sum(len(g) for _, g in GROUPS)
    clips = [c for _, group in GROUPS + DEF_GROUPS for c in group]
    entries, data = [], b''
    for name, _ in clips:
        samples = load(os.path.join(wav_dir, name + '.wav'),
                       trim=name.startswith(('turret', 'defect')),
                       max_s=MAX_SECONDS.get(name))
        enc = ima_adpcm.encode(samples)
        entries.append((len(data), len(samples)))
        data += enc
        print(f'{name}: {len(samples) / RATE:.2f}s {len(enc)} bytes')

    for path, n in ((out_bin, len(clips)), (out_lite, n_regular)):
        head = struct.pack('<HH', n, 0)
        base = 4 + 8 * n
        for off, k in entries[:n]:
            head += struct.pack('<II', base + off, k)
        end = entries[n][0] if n < len(entries) else len(data)
        open(path, 'wb').write(head + data[:end])
        print(f'{path}: {n} clips, {len(head) + end} bytes')

    with open(out_h, 'w') as h:
        h.write('// Generated by tools/convert_audio.py -- clip ids in resources/voices.bin\n')
        h.write('#pragma once\n\n')
        for i, (_, cname) in enumerate(clips):
            h.write(f'#define VOICE_{cname} {i}\n')
        h.write('\n')
        first = 0
        for gname, group in GROUPS + DEF_GROUPS:
            h.write(f'#define VOICE_{gname}_FIRST {first}\n#define VOICE_{gname}_COUNT {len(group)}\n')
            first += len(group)
        h.write(f'#define VOICE_RATE {RATE}\n')


if __name__ == '__main__':
    main()
