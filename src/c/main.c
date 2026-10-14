// Portal Turret watchface.
//
// Default view: close-up on the turret's eye, which doubles as the clock.
// The lens is a ring of 24 red wedges like the real turret's; the wedge
// pointing at the current minute glows bright red along its whole length (the
// long hand), the one at the hour only on its inner half (the short hand).
// The time is printed on the shell below the eye. A wrist flick zooms out to
// show the whole turret, then its side panels slide open (the kick rocks
// it onto one foot and back until it settles) and it scans the room, sweeping the
// panels and its laser sight around. After a few seconds
// it all reverses.
//
// The turret is a flat-shaded low-poly mesh (resources/turret.bin, produced by
// tools/convert_model.py) drawn straight into the framebuffer with a
// painter's-algorithm scanline rasterizer and 4x4 ordered dithering, since
// the 64-colour palette only has four grey levels. The eye is drawn on top
// with the same rasterizer, projected through the same camera so it stays
// glued to the model while zooming. Model pixels that the eye would cover are
// never drawn.
//
// The CPU has no FPU, so everything per-vertex and per-pixel is fixed point;
// floats are only used for a handful of per-frame camera values.
//
// The mesh (~60KB with scratch buffers) is only held in RAM while it is being
// drawn: during the flick animation, or for the single redraw each minute.

#include <pebble.h>

#include "audio.h"
#include "voices.h"

// ---------------------------------------------------------------------------
// Model resource layout (little-endian, see tools/convert_model.py)

#define MODEL_MAGIC "TRT1"
#define MAX_GROUPS 4
#define MAX_PAL 16
#define PAL_EMISSIVE 0x01
#define FLAG_CULL 0x0001

typedef struct __attribute__((packed)) {
  char magic[4];
  uint16_t nverts;
  uint16_t ntris;
  uint8_t ngroups;
  uint8_t npal;
  uint16_t flags;
  float vscale;               // vertex = int16 * vscale
  float center[3];            // bbox centre, panels open
  float height;               // bbox height
  float width;                // bbox width, panels open
  float eye[3];               // eye centre (eye faces +z, up is +y)
  float eye_r;                // eye housing radius
  float group_off[MAX_GROUPS][3]; // closed -> open translation per group
  uint8_t pal[MAX_PAL][4];    // r, g, b, flags
} ModelHeader;                // 164 bytes

#define TRI_TWO_SIDED 0x01

typedef struct __attribute__((packed)) {
  uint16_t v[3];
  uint8_t col;
  uint8_t flags;   // TRI_TWO_SIDED: thin part seen from both sides, never cull
} ModelTri;

// The header is tiny and always resident; the rest is loaded on demand.
static ModelHeader s_hdr;
static bool s_hdr_ok;

static uint8_t *s_body;
static const int16_t *s_verts;    // nverts * 3
static const ModelTri *s_tris;    // ntris
static const int8_t *s_normals;   // ntris * 3
static const uint8_t *s_vgroup;   // nverts
static int32_t s_pivot[MAX_GROUPS][3]; // per-group centroid, the panels pivot here

typedef struct {
  int32_t x, y;  // screen, 24.8 fixed point
  int32_t z;     // camera depth, model units
} ScreenVert;

#define IDX_BITS 11  // draw-list entry = depth << IDX_BITS | triangle index

static ScreenVert *s_sv;
static uint32_t *s_items;
static uint32_t *s_items_tmp;

// shaded dither patterns, see shade()
#define INTEN_SHIFT 2
#define INTEN_LEVELS 72
static uint8_t (*s_pat_cache)[INTEN_LEVELS][16];  // [MAX_PAL]
static uint8_t (*s_pat_ok)[INTEN_LEVELS];

// ---------------------------------------------------------------------------
// Animation state

#define FRAME_MS 33
#define ZOOM_MS 900
#define WINGS_MS 450
#define HOLD_MS 7000

// Store captures (tools/capture_store.py): build with -DSTORE_CAPTURE and the
// face flicks by itself, stepping the animation on a fixed clock and holding
// each frame long enough for the emulator to screenshot it.
#ifdef STORE_CAPTURE
#define STORE_TIME
#define CAPTURE_DT_MS 80        // animation time per GIF frame
#define CAPTURE_FRAME_MS 3000   // real time each frame stays on screen
#undef HOLD_MS
#define HOLD_MS 3400
static int s_cap_frame;
static uint64_t s_cap_clock;
#endif
#define SCAN_RAMP_MS 400
#define SCAN_YAW (TRIG_MAX_ANGLE * 22 / 360)   // panels and laser sweep +-22 deg
#define SCAN_PITCH (TRIG_MAX_ANGLE * 9 / 360)  // ... and nod +-9 deg
#define SCAN_YAW_MS 2800                       // sweep periods
#define SCAN_PITCH_MS 1900
#define LASER_TILT (TRIG_MAX_ANGLE * 9 / 360)  // the laser aims a bit down
#define LASER_LEN 2.6f                         // model units, unless it hits the floor
#define TIP_MS 2400                            // rocking after the panels open
#define TIP_MAX (TRIG_MAX_ANGLE * 13 / 360)    // first lean, 13 degrees
#define TIP_PERIOD_MS 1000
#define TIP_DECAY_MS 420                       // amplitude falls to 1/e this fast
#define TIP_FOOT 0.16f                         // pivot: a foot this far off centre
#define YAW_MAX (TRIG_MAX_ANGLE / 18)  // ~20 degrees of idle sway
#define PITCH_MAX (TRIG_MAX_ANGLE / 30) // zoomed out, look down 12 degrees

static Window *s_window;
static Layer *s_canvas;
static AppTimer *s_timer;
static GFont s_font;

static int32_t s_zoom_p;   // linear progress 0..1000
static int32_t s_wing_p;   // linear progress 0..1000
static int32_t s_scan_p;   // scan amplitude 0..1000
static uint32_t s_scan_ms; // time spent scanning, drives the sweep
static int32_t s_tip_ms = TIP_MS; // time since the panels started opening, drives the rocking
static int s_tip_dir;      // +1 leans left first, -1 right

// the whole turret's sideways lean this frame (about z, through a foot)
static int32_t s_roll_s, s_roll_c, s_roll_px;
static bool s_roll_on;
static bool s_out;         // heading out (zoomed out, panels open)
static uint64_t s_hold_until;
static uint64_t s_last_ms;
static uint32_t s_sway_ms; // time spent zoomed out, drives the sway

static struct tm s_now;
static char s_time_buf[8];

// ---------------------------------------------------------------------------
// Settings, from the phone (src/pkjs), kept in persistent storage

#define WALL_COLS 8
#define WALL_ROWS 4
#define FLOOR_COLS 16   // floor tiles are half a wall panel
#define FLOOR_ROWS 7
#define ROOM_TILES (WALL_COLS * WALL_ROWS + FLOOR_COLS * FLOOR_ROWS)

// A byte per tile (wall rows bottom-up, then floor rows back to front): bits
// 0-3 say which quarters are dark (bit = x half + 2 * row half, both counted
// from the bottom-left / back-left), TILE_SPLIT that it shows as four small
// tiles. A whole dark tile is 0x0F.
#define TILE_SPLIT 0x10
#define TILE_DARK 0x0F

#define SETTINGS_KEY 1
#define SETTINGS_VERSION 2

typedef struct __attribute__((packed)) {
  uint8_t version;
  uint8_t show_time;           // the time under the eye
  uint8_t volume;              // 0..100, 0 = silent
  uint8_t room[ROOM_TILES];
} Settings;

// version 1: a bit per tile
#define ROOM_BYTES_V1 ((ROOM_TILES + 7) / 8)
typedef struct __attribute__((packed)) {
  uint8_t version, show_time, volume;
  uint8_t room[ROOM_BYTES_V1];
} SettingsV1;

static Settings s_cfg;

// the look of the reference test chamber: the right part of the wall and the
// floor strip in front of it are dark
static void default_settings(void) {
  memset(&s_cfg, 0, sizeof(s_cfg));
  s_cfg.version = SETTINGS_VERSION;
  s_cfg.show_time = 1;
  s_cfg.volume = 70;
  for (int r = 0; r < WALL_ROWS; r++) {
    for (int c = 5; c < WALL_COLS; c++) s_cfg.room[r * WALL_COLS + c] = TILE_DARK;
  }
  for (int r = 0; r < 2; r++) {
    for (int c = 10; c < FLOOR_COLS; c++) {
      s_cfg.room[WALL_COLS * WALL_ROWS + r * FLOOR_COLS + c] = TILE_DARK;
    }
  }
}

static void load_settings(void) {
  default_settings();
  union { Settings v2; SettingsV1 v1; } saved;
  int n = persist_read_data(SETTINGS_KEY, &saved, sizeof(saved));
  if (n == (int)sizeof(Settings) && saved.v2.version == SETTINGS_VERSION) {
    s_cfg = saved.v2;
  } else if (n == (int)sizeof(SettingsV1) && saved.v1.version == 1) {
    s_cfg.show_time = saved.v1.show_time;
    s_cfg.volume = saved.v1.volume;
    for (int i = 0; i < ROOM_TILES; i++) {
      s_cfg.room[i] = (saved.v1.room[i >> 3] >> (i & 7)) & 1 ? TILE_DARK : 0;
    }
  }
#ifdef STORE_ROOM
  // a showcase room: dark chamber, a white band on the wall, checkered floor
  for (int i = 0; i < ROOM_TILES; i++) s_cfg.room[i] = TILE_DARK;
  for (int c = 0; c < WALL_COLS; c++) s_cfg.room[2 * WALL_COLS + c] = (c & 1) ? 0 : TILE_SPLIT | 0x9;
  for (int r = 0; r < FLOOR_ROWS; r++) {
    for (int c = 0; c < FLOOR_COLS; c++) {
      if ((r + c) & 1) s_cfg.room[WALL_COLS * WALL_ROWS + r * FLOOR_COLS + c] = 0;
    }
  }
#endif
  audio_set_volume(s_cfg.volume);
}

static uint64_t now_ms(void) {
  time_t s;
  uint16_t ms;
  time_ms(&s, &ms);
  return (uint64_t)s * 1000 + ms;
}

// smootherstep on 0..1000, returned as float 0..1
static float ease(int32_t p) {
  float t = p / 1000.0f;
  return t * t * t * (t * (t * 6 - 15) + 10);
}

// panels pop out quickly and settle with a small overshoot
static float ease_back_out(int32_t p) {
  float t = p / 1000.0f - 1.0f;
  const float k = 1.4f;
  return 1.0f + t * t * ((k + 1) * t + k);
}

static bool animating(void) {
  return s_out || s_zoom_p > 0 || s_wing_p > 0 || s_scan_p > 0 || s_tip_ms < TIP_MS;
}

// ---------------------------------------------------------------------------
// Model loading

static void release_model(void) {
  free(s_body);
  free(s_sv);
  free(s_items);
  free(s_items_tmp);
  free(s_pat_cache);
  free(s_pat_ok);
  s_pat_cache = NULL;
  s_pat_ok = NULL;
  s_body = NULL;
  s_sv = NULL;
  s_items = NULL;
  s_items_tmp = NULL;
}

static bool ensure_model(void) {
  if (s_body) return true;
  if (!s_hdr_ok) return false;
  audio_pump();
  ResHandle rh = resource_get_handle(RESOURCE_ID_TURRET_MODEL);
  size_t size = resource_size(rh) - sizeof(ModelHeader);
  s_body = malloc(size);
  s_sv = malloc(sizeof(ScreenVert) * s_hdr.nverts);
  s_items = malloc(sizeof(uint32_t) * s_hdr.ntris);
  s_items_tmp = malloc(sizeof(uint32_t) * s_hdr.ntris);
  s_pat_cache = malloc(MAX_PAL * INTEN_LEVELS * 16);
  s_pat_ok = calloc(MAX_PAL, INTEN_LEVELS);
  if (!s_body || !s_sv || !s_items || !s_items_tmp || !s_pat_cache || !s_pat_ok) {
    APP_LOG(APP_LOG_LEVEL_ERROR, "model alloc failed (heap %d)", (int)heap_bytes_free());
    release_model();
    return false;
  }
  resource_load_byte_range(rh, sizeof(ModelHeader), s_body, size);
  uint8_t *p = s_body;
  s_verts = (const int16_t *)p;   p += s_hdr.nverts * 6;
  s_tris = (const ModelTri *)p;   p += s_hdr.ntris * sizeof(ModelTri);
  s_normals = (const int8_t *)p;  p += s_hdr.ntris * 3;
  s_vgroup = p;
  audio_pump();

  int32_t sum[MAX_GROUPS][3] = { { 0 } };
  int32_t cnt[MAX_GROUPS] = { 0 };
  for (int i = 0; i < s_hdr.nverts; i++) {
    uint8_t g = s_vgroup[i] < MAX_GROUPS ? s_vgroup[i] : 0;
    for (int k = 0; k < 3; k++) sum[g][k] += s_verts[i * 3 + k];
    cnt[g]++;
  }
  for (int g = 0; g < MAX_GROUPS; g++) {
    for (int k = 0; k < 3; k++) s_pivot[g][k] = cnt[g] ? sum[g][k] / cnt[g] : 0;
  }
  return true;
}

static void load_header(void) {
  ResHandle rh = resource_get_handle(RESOURCE_ID_TURRET_MODEL);
  resource_load_byte_range(rh, 0, (uint8_t *)&s_hdr, sizeof(ModelHeader));
  s_hdr_ok = memcmp(s_hdr.magic, MODEL_MAGIC, 4) == 0
             && s_hdr.ntris < (1 << IDX_BITS);
}

// ---------------------------------------------------------------------------
// Camera (model units are the int16 vertex units, "q")

typedef struct {
  int32_t tx, ty, tz;     // look-at target
  int32_t dist;           // camera distance from target
  int64_t k12;            // projection factor << 12 (see project)
  int32_t cx256, cy256;   // screen anchor, 24.8
  int32_t ccx, ccz;       // yaw pivot (model centre)
  int32_t ys, yc;         // yaw sin/cos (TRIG_MAX_RATIO)
  int32_t ps, pc;         // camera pitch (looking down) sin/cos
  int32_t ex, ey, ez;     // eye centre, yawed
  int32_t eye_r;          // eye radius
  float scale;            // pixels per model unit at the target's depth
} Camera;

static Camera s_cam;

static inline void yaw_q(int32_t *x, int32_t *z) {
  int32_t dx = *x - s_cam.ccx, dz = *z - s_cam.ccz;
  *x = s_cam.ccx + (int32_t)(((int64_t)dx * s_cam.yc + (int64_t)dz * s_cam.ys) >> 16);
  *z = s_cam.ccz + (int32_t)(((int64_t)dz * s_cam.yc - (int64_t)dx * s_cam.ys) >> 16);
}

static inline void project(int32_t x, int32_t y, int32_t z, ScreenVert *out) {
  int32_t dy = y - s_cam.ty, dz = z - s_cam.tz;
  if (s_cam.ps) {  // tilt about the target: far things rise, near things sink
    int32_t py = (int32_t)(((int64_t)dy * s_cam.pc - (int64_t)dz * s_cam.ps) >> 16);
    dz = (int32_t)(((int64_t)dz * s_cam.pc + (int64_t)dy * s_cam.ps) >> 16);
    dy = py;
  }
  int32_t zc = s_cam.dist - dz;
  if (zc < s_cam.dist / 16) zc = s_cam.dist / 16;
  int64_t f = s_cam.k12 / zc;
  out->x = s_cam.cx256 + (int32_t)(((int64_t)(x - s_cam.tx) * f) >> 12);
  out->y = s_cam.cy256 - (int32_t)(((int64_t)dy * f) >> 12);
  out->z = zc;
}

// no libm on the watch: small float log2/exp2 approximations
static float my_log2(float x) {
  union { float f; uint32_t i; } u = { x };
  float e = (float)(int32_t)((u.i >> 23) & 0xFF) - 127.0f;
  u.i = (u.i & 0x007FFFFF) | 0x3F800000;  // mantissa in [1, 2)
  float t = (u.f - 1.0f) / (u.f + 1.0f);  // ln(m) = 2 atanh(t), |t| <= 1/3
  float t2 = t * t;
  float ln = 2.0f * t * (1.0f + t2 * (1.0f / 3 + t2 * (1.0f / 5 + t2 * (1.0f / 7 + t2 / 9))));
  return e + ln * 1.44269504f;
}

static float my_exp2(float x) {
  int32_t xi = (int32_t)x;
  if (x < 0 && (float)xi != x) xi--;  // floor
  float f = x - xi;                     // [0, 1)
  float p = 1.0f + f * (0.69314718f + f * (0.24022650f + f * (0.05550411f
            + f * (0.00961813f + f * 0.00133336f))));
  union { float f; uint32_t i; } u = { p };
  u.i += (uint32_t)xi << 23;
  return u.f;
}

#if defined(PBL_ROUND)
static float my_sqrt(float x) {
  float r = x > 1 ? x : 1;
  for (int i = 0; i < 12; i++) r = 0.5f * (r + x / r);
  return r;
}
#endif

// Close-up layout: eye radius in pixels
#if defined(PBL_ROUND)
#define EYE_PX 76.0f
#else
#define EYE_PX 74.0f
#endif

// lean angle (TRIG_MAX_ANGLE, counter-clockwise on screen): a damped sway
static int32_t tip_angle(void) {
  if (s_tip_ms >= TIP_MS) return 0;
  float t = (float)s_tip_ms;
  float decay = my_exp2(-t / (TIP_DECAY_MS * 0.6931472f));
  int32_t ph = (int32_t)((int64_t)s_tip_ms * TRIG_MAX_ANGLE / TIP_PERIOD_MS);
  return (int32_t)(s_tip_dir * (float)TIP_MAX * decay * sin_lookup(ph) / TRIG_MAX_RATIO);
}

static void setup_roll(void) {
  int32_t a = tip_angle();
  s_roll_on = a != 0;
  s_roll_s = sin_lookup(a);
  s_roll_c = cos_lookup(a);
  // it rocks on the foot it leans towards
  float foot = TIP_FOOT * (a > 0 ? -1 : 1);
  s_roll_px = (int32_t)((s_hdr.center[0] + foot) / s_hdr.vscale);
}

// lean a model-space point (the feet are at y = 0)
static inline void roll_q(int32_t *x, int32_t *y) {
  if (!s_roll_on) return;
  int32_t dx = *x - s_roll_px;
  int32_t nx = (int32_t)(((int64_t)dx * s_roll_c - (int64_t)*y * s_roll_s) >> 16);
  *y = (int32_t)(((int64_t)dx * s_roll_s + (int64_t)*y * s_roll_c) >> 16);
  *x = s_roll_px + nx;
}

static void setup_camera(GRect bounds, float zoom) {
  const ModelHeader *h = &s_hdr;
  float w = bounds.size.w, ht = bounds.size.h;
  float iv = 1.0f / h->vscale;

  int32_t yaw = (int32_t)(sin_lookup((int32_t)(s_sway_ms * (TRIG_MAX_ANGLE / 7000)))
                          * (int64_t)YAW_MAX / TRIG_MAX_RATIO * zoom);
  s_cam.ys = sin_lookup(yaw);
  s_cam.yc = cos_lookup(yaw);
  int32_t pitch = (int32_t)(PITCH_MAX * zoom);
  s_cam.ps = sin_lookup(pitch);
  s_cam.pc = cos_lookup(pitch);
  s_cam.ccx = (int32_t)(h->center[0] * iv);
  s_cam.ccz = (int32_t)(h->center[2] * iv);

  float s0 = EYE_PX / h->eye_r;
#if defined(PBL_ROUND)
  // fit the bounding box's corners inside the circle
  float hh = h->height / 2, hw = h->width / 2;
  float s1 = (w < ht ? w : ht) * 0.45f / my_sqrt(hh * hh + hw * hw);
#else
  float s1a = ht * 0.80f / h->height;
  float s1b = w * 0.90f / h->width;
  float s1 = s1a < s1b ? s1a : s1b;
#endif
  // Zoom exponentially (constant perceived speed), and move the target and
  // screen anchor by how far the view size has grown, so the point under
  // the camera glides from the eye to the body without drifting.
  s_cam.scale = s0 * my_exp2(zoom * my_log2(s1 / s0));
  float pan = (1.0f / s_cam.scale - 1.0f / s0) / (1.0f / s1 - 1.0f / s0);

  s_cam.ex = (int32_t)(h->eye[0] * iv);
  s_cam.ey = (int32_t)(h->eye[1] * iv);
  s_cam.ez = (int32_t)(h->eye[2] * iv);
  yaw_q(&s_cam.ex, &s_cam.ez);
  s_cam.eye_r = (int32_t)(h->eye_r * iv);
  int32_t eye_tx = s_cam.ex, eye_ty = s_cam.ey;

  // aim a little below the middle: the downward tilt pushes the feet low
  int32_t cx = s_cam.ccx, cy = (int32_t)((h->center[1] - 0.07f * h->height) * iv), cz = s_cam.ccz;
  s_cam.tx = eye_tx + (int32_t)((cx - eye_tx) * pan);
  s_cam.ty = eye_ty + (int32_t)((cy - eye_ty) * pan);
  s_cam.tz = s_cam.ez + (int32_t)((cz - s_cam.ez) * pan);
  s_cam.dist = (int32_t)(h->height * 2.5f * iv);

  // the eye leans with the turret (the camera target doesn't)
  s_cam.ex = (int32_t)(h->eye[0] * iv);
  s_cam.ey = (int32_t)(h->eye[1] * iv);
  s_cam.ez = (int32_t)(h->eye[2] * iv);
  roll_q(&s_cam.ex, &s_cam.ey);
  yaw_q(&s_cam.ex, &s_cam.ez);

  s_cam.cx256 = (int32_t)(w * 128.0f);
  s_cam.cy256 = (int32_t)(ht * 128.0f);
  // pixels per q unit at the target depth, 24.8, times dist, << 12
  s_cam.k12 = (int64_t)(s_cam.scale * h->vscale * 256.0f * s_cam.dist * 4096.0f);
}

// point on the eye disc: clock angle (TRIG_MAX_ANGLE units, 0 = 12 o'clock)
// and radius as a fraction (x1000) of the eye radius
static void eye_pt(int32_t angle, int32_t r1000, ScreenVert *out) {
  angle -= tip_angle();
  int32_t rr = s_cam.eye_r * r1000 / 1000;
  int32_t ox = (int32_t)(((int64_t)rr * sin_lookup(angle)) >> 16);
  int32_t oy = (int32_t)(((int64_t)rr * cos_lookup(angle)) >> 16);
  int32_t x = s_cam.ex + (int32_t)(((int64_t)ox * s_cam.yc) >> 16);
  int32_t z = s_cam.ez - (int32_t)(((int64_t)ox * s_cam.ys) >> 16);
  project(x, s_cam.ey + oy, z, out);
}

// ---------------------------------------------------------------------------
// Eye mask: an ellipse (screen-aligned, 24.8) the eye will paint over, so
// the model rasterizer can skip it.

static bool s_mask_on;
static int32_t s_mx, s_my, s_ma, s_mb;
static int16_t s_mask_l[260], s_mask_r[260];

// first pixel index whose centre is >= v (v in 24.8)
static inline int32_t ceil_px(int32_t v) {
  return (v - 128 + 255) >> 8;
}

static uint32_t isqrt(uint32_t n) {
  uint32_t r = 0, bit = 1u << 30;
  while (bit > n) bit >>= 2;
  while (bit) {
    if (n >= r + bit) { n -= r + bit; r = (r >> 1) + bit; }
    else r >>= 1;
    bit >>= 2;
  }
  return r;
}

#define EYE_OUTER 1220   // housing rim radius (x1000 of eye radius)
#define EYE_MASK 1180    // slightly inside it, so no gap can show

static void setup_mask(int fb_h) {
  ScreenVert c, top, right;
  eye_pt(0, 0, &c);
  eye_pt(0, EYE_MASK, &top);
  eye_pt(TRIG_MAX_ANGLE / 4, EYE_MASK, &right);
  s_mx = c.x;
  s_my = c.y;
  s_ma = right.x - c.x;
  s_mb = c.y - top.y;
  if (s_ma < 0) s_ma = -s_ma;
  s_mask_on = s_mb >= 6 * 256 && s_ma >= 6 * 256 && s_mb < 40000 && s_ma < 40000;
  if (!s_mask_on) return;
  for (int y = 0; y < fb_h && y < 260; y++) {
    int32_t dy = (y << 8) + 128 - s_my;
    s_mask_l[y] = 1;
    s_mask_r[y] = 0;
    if (dy <= -s_mb || dy >= s_mb) continue;
    int32_t hw = (int32_t)((int64_t)s_ma * isqrt((uint32_t)(s_mb * s_mb - dy * dy)) / s_mb);
    s_mask_l[y] = ceil_px(s_mx - hw);
    s_mask_r[y] = ceil_px(s_mx + hw) - 1;
  }
}

static bool in_mask(const ScreenVert *v) {
  int32_t dx = v->x - s_mx, dy = v->y - s_my;
  if (dx <= -s_ma || dx >= s_ma || dy <= -s_mb || dy >= s_mb) return false;
  int64_t a2 = (int64_t)s_ma * s_ma, b2 = (int64_t)s_mb * s_mb;
  return (int64_t)dx * dx * b2 + (int64_t)dy * dy * a2 < a2 * b2;
}

// ---------------------------------------------------------------------------
// Rasterizer

static const uint8_t BAYER[16] = {
  0, 8, 2, 10,
  12, 4, 14, 6,
  3, 11, 1, 9,
  15, 7, 13, 5,
};

// light direction (camera space), scaled to 256
#define LX (-90)
#define LY (150)
#define LZ (180)
#define AMBIENT 90
#define DIFFUSE 190

static void build_pattern(uint8_t pal_idx, int32_t inten, uint8_t pat[16]) {
  const uint8_t *c = s_hdr.pal[pal_idx];
  int32_t lo[3], fr[3];
  for (int i = 0; i < 3; i++) {
    int32_t v = c[i] * inten / 256;
    if (v > 255) v = 255;
    int32_t lvl = v * 3;          // 0..765
    lo[i] = lvl / 255;
    fr[i] = (lvl % 255) * 16 / 255;
  }
  for (int t = 0; t < 16; t++) {
    uint8_t r = lo[0] + (fr[0] > BAYER[t]);
    uint8_t g = lo[1] + (fr[1] > BAYER[t]);
    uint8_t b = lo[2] + (fr[2] > BAYER[t]);
    if (r > 3) r = 3;
    if (g > 3) g = 3;
    if (b > 3) b = 3;
    pat[t] = 0xC0 | (r << 4) | (g << 2) | b;
  }
}

// Dither patterns per (palette entry, brightness step), built on first use
// and kept with the model: most triangles share a handful of them.
_Static_assert((AMBIENT + DIFFUSE) >> INTEN_SHIFT < INTEN_LEVELS, "shade levels");

static const uint8_t *shade(uint8_t pal_idx, int32_t nx, int32_t ny, int32_t nz) {
  if (pal_idx >= MAX_PAL) pal_idx = 0;
  int32_t inten = 256;
  if (!(s_hdr.pal[pal_idx][3] & PAL_EMISSIVE)) {
    int32_t d = (nx * LX + ny * LY + nz * LZ) / 127;  // /127 for int8 normals
    if (d < 0) d = 0;
    inten = AMBIENT + d * DIFFUSE / 256;
  }
  int lv = inten >> INTEN_SHIFT;
  if (lv >= INTEN_LEVELS) lv = INTEN_LEVELS - 1;
  uint8_t *pat = s_pat_cache[pal_idx][lv];
  if (!s_pat_ok[pal_idx][lv]) {
    build_pattern(pal_idx, lv << INTEN_SHIFT, pat);
    s_pat_ok[pal_idx][lv] = 1;
  }
  return pat;
}

// dither of two palette colours: `mix`/16 of b over a
static void mix_pattern(GColor a, GColor b, int mix, uint8_t pat[16]) {
  for (int t = 0; t < 16; t++) pat[t] = BAYER[t] < mix ? b.argb : a.argb;
}

// p is the pattern's 4-pixel row; the middle of the span goes 4 pixels per store
static inline void fill_span(uint8_t *row, int32_t x0, int32_t x1, const uint8_t *p) {
  int32_t x = x0;
  if (x1 - x0 < 16) {  // short spans (most triangles): plain loop
    for (; x <= x1; x++) row[x] = p[x & 3];
    return;
  }
  while ((uintptr_t)(row + x) & 3) { row[x] = p[x & 3]; x++; }
  if (x + 3 <= x1) {
    uint32_t w = p[x & 3] | (p[(x + 1) & 3] << 8) | (p[(x + 2) & 3] << 16)
               | ((uint32_t)p[(x + 3) & 3] << 24);
    uint32_t *wp = (uint32_t *)(row + x);
    for (; x + 3 <= x1; x += 4) *wp++ = w;
  }
  for (; x <= x1; x++) row[x] = p[x & 3];
}

// framebuffer rows, looked up once per frame instead of once per triangle row
#define MAX_ROWS 260
static uint8_t *s_row_data[MAX_ROWS];
static int16_t s_row_min[MAX_ROWS], s_row_max[MAX_ROWS];

static void cache_rows(GBitmap *fb) {
  int h = gbitmap_get_bounds(fb).size.h;
  for (int y = 0; y < h && y < MAX_ROWS; y++) {
    GBitmapDataRowInfo row = gbitmap_get_data_row_info(fb, y);
    s_row_data[y] = row.data;
    s_row_min[y] = row.min_x;
    s_row_max[y] = row.max_x;
  }
}

// dx/dy in 16.16 (dy > 0). No 64-bit division: there is no hardware for it,
// so it goes through a 32-bit reciprocal and a multiply instead.
static inline int64_t slope(int32_t dx, int32_t dy) {
  uint32_t inv = (1u << 30) / (uint32_t)dy;
  return ((int64_t)dx * inv) >> 14;
}

static void raster_tri(GBitmap *fb, int fb_h, const ScreenVert *a,
                       const ScreenVert *b, const ScreenVert *c,
                       const uint8_t pat[16], bool masked) {
  const ScreenVert *t;
  if (a->y > b->y) { t = a; a = b; b = t; }
  if (b->y > c->y) { t = b; b = c; c = t; }
  if (a->y > b->y) { t = a; a = b; b = t; }
  if (c->y == a->y) return;

  int32_t y_start = ceil_px(a->y);
  int32_t y_end = ceil_px(c->y);
  if (y_start < 0) y_start = 0;
  if (y_end > fb_h) y_end = fb_h;
  if (y_end > MAX_ROWS) y_end = MAX_ROWS;
  if (y_start >= y_end) return;

  int64_t d02 = slope(c->x - a->x, c->y - a->y);
  int64_t d01 = b->y > a->y ? slope(b->x - a->x, b->y - a->y) : 0;
  int64_t d12 = c->y > b->y ? slope(c->x - b->x, c->y - b->y) : 0;

  for (int32_t y = y_start; y < y_end; y++) {
    int32_t yc = (y << 8) + 128;
    int32_t xa = a->x + (int32_t)(((int64_t)(yc - a->y) * d02) >> 16);
    int32_t xb;
    if (yc < b->y) {
      xb = a->x + (int32_t)(((int64_t)(yc - a->y) * d01) >> 16);
    } else {
      xb = b->x + (int32_t)(((int64_t)(yc - b->y) * d12) >> 16);
    }
    if (xa > xb) { int32_t tmp = xa; xa = xb; xb = tmp; }
    int32_t x0 = ceil_px(xa);
    int32_t x1 = ceil_px(xb) - 1;
    if (x0 < s_row_min[y]) x0 = s_row_min[y];
    if (x1 > s_row_max[y]) x1 = s_row_max[y];
    if (x0 > x1) continue;
    uint8_t *data = s_row_data[y];
    const uint8_t *p = &pat[(y & 3) * 4];
    if (masked && s_mask_l[y] <= s_mask_r[y]) {
      int32_t ml = s_mask_l[y], mr = s_mask_r[y];
      fill_span(data, x0, x1 < ml - 1 ? x1 : ml - 1, p);
      fill_span(data, x0 > mr + 1 ? x0 : mr + 1, x1, p);
    } else {
      fill_span(data, x0, x1, p);
    }
  }
}

// LSD radix sort, ascending
static void sort_items(uint32_t *a, uint32_t *tmp, int n) {
  uint16_t count[256];
  for (int shift = 0; shift < 32; shift += 8) {
    memset(count, 0, sizeof(count));
    for (int i = 0; i < n; i++) count[(a[i] >> shift) & 0xFF]++;
    uint16_t sum = 0;
    for (int i = 0; i < 256; i++) { uint16_t c = count[i]; count[i] = sum; sum += c; }
    for (int i = 0; i < n; i++) tmp[count[(a[i] >> shift) & 0xFF]++] = a[i];
    uint32_t *sw = a; a = tmp; tmp = sw;
  }
  // four passes: the result is back in the caller's array
}

// current scan direction: yaw (+ = turret's left, screen right) and pitch
// (+ = down), TRIG_MAX_ANGLE units
static void scan_angles(int32_t *yaw, int32_t *pitch) {
  float amp = ease(s_scan_p);
  *yaw = (int32_t)(sin_lookup((int32_t)((uint64_t)s_scan_ms * TRIG_MAX_ANGLE / SCAN_YAW_MS))
                   * (int64_t)SCAN_YAW / TRIG_MAX_RATIO * amp);
  *pitch = (int32_t)(sin_lookup((int32_t)((uint64_t)s_scan_ms * TRIG_MAX_ANGLE / SCAN_PITCH_MS))
                     * (int64_t)SCAN_PITCH / TRIG_MAX_RATIO * amp);
}

// rotation by pitch (about x) then yaw (about y), sin/cos in TRIG_MAX_RATIO
typedef struct { int32_t ps, pc, ws, wc; } Rot;

static inline void rot_apply(const Rot *r, int32_t *x, int32_t *y, int32_t *z) {
  int32_t ny = (int32_t)(((int64_t)*y * r->pc - (int64_t)*z * r->ps) >> 16);
  int32_t nz = (int32_t)(((int64_t)*y * r->ps + (int64_t)*z * r->pc) >> 16);
  int32_t nx = (int32_t)(((int64_t)*x * r->wc + (int64_t)nz * r->ws) >> 16);
  *z = (int32_t)(((int64_t)nz * r->wc - (int64_t)*x * r->ws) >> 16);
  *x = nx;
  *y = ny;
}

static void rot_make(Rot *r, int32_t yaw, int32_t pitch) {
  r->ps = sin_lookup(pitch);
  r->pc = cos_lookup(pitch);
  r->ws = sin_lookup(yaw);
  r->wc = cos_lookup(yaw);
}

static void render_model(GBitmap *fb, GRect bounds, float wings) {
  const ModelHeader *h = &s_hdr;
  float iv = 1.0f / h->vscale;
  float open = wings - 1.0f;  // 0 = as modelled (open), -1 = closed
  int32_t off[MAX_GROUPS][3];
  for (int g = 0; g < MAX_GROUPS; g++) {
    for (int k = 0; k < 3; k++) off[g][k] = (int32_t)(h->group_off[g][k] * open * iv);
  }

  // scanning: the side panels (groups 1, 2) turn together about their centres
  bool scan = s_scan_p > 0;
  Rot rot;
  if (scan) {
    int32_t yaw, pitch;
    scan_angles(&yaw, &pitch);
    rot_make(&rot, yaw, pitch);
  }

  for (int i = 0; i < h->nverts; i++) {
    const int16_t *v = &s_verts[i * 3];
    uint8_t g = s_vgroup[i];
    if (g >= MAX_GROUPS) g = 0;
    int32_t x = v[0], y = v[1], z = v[2];
    if (scan && (g == 1 || g == 2)) {
      const int32_t *pv = s_pivot[g];
      x -= pv[0]; y -= pv[1]; z -= pv[2];
      rot_apply(&rot, &x, &y, &z);
      x += pv[0]; y += pv[1]; z += pv[2];
    }
    x += off[g][0]; y += off[g][1]; z += off[g][2];
    roll_q(&x, &y);
    yaw_q(&x, &z);
    project(x, y, z, &s_sv[i]);
  }

  int32_t W = bounds.size.w, H = bounds.size.h;
  int n = 0;
  bool cull = h->flags & FLAG_CULL;
  for (int i = 0; i < h->ntris; i++) {
    const ModelTri *t = &s_tris[i];
    const ScreenVert *a = &s_sv[t->v[0]], *b = &s_sv[t->v[1]], *c = &s_sv[t->v[2]];
    if (cull && !(t->flags & TRI_TWO_SIDED)) {
      int64_t cross = (int64_t)(b->x - a->x) * (c->y - a->y)
                    - (int64_t)(b->y - a->y) * (c->x - a->x);
      if (cross >= 0) continue;
    }
    // trivially off-screen?
    int32_t minx = a->x, maxx = a->x, miny = a->y, maxy = a->y;
    if (b->x < minx) { minx = b->x; }
    if (b->x > maxx) { maxx = b->x; }
    if (c->x < minx) { minx = c->x; }
    if (c->x > maxx) { maxx = c->x; }
    if (b->y < miny) { miny = b->y; }
    if (b->y > maxy) { maxy = b->y; }
    if (c->y < miny) { miny = c->y; }
    if (c->y > maxy) { maxy = c->y; }
    if (maxx < 0 || maxy < 0 || minx > (W << 8) || miny > (H << 8)) continue;
    // hidden behind the eye?
    if (s_mask_on && in_mask(a) && in_mask(b) && in_mask(c)) continue;
    uint32_t depth = (uint32_t)(a->z + b->z + c->z) >> 2;
    s_items[n++] = (depth << IDX_BITS) | i;
  }
  audio_pump();
  sort_items(s_items, s_items_tmp, n);

  int fb_h = gbitmap_get_bounds(fb).size.h;
  int32_t ys = s_cam.ys, yc = s_cam.yc;
  for (int k = n - 1; k >= 0; k--) {  // far first
    int idx = s_items[k] & ((1 << IDX_BITS) - 1);
    const ModelTri *t = &s_tris[idx];
    if ((k & 255) == 0) audio_pump();
    const int8_t *nm = &s_normals[idx * 3];
    int32_t mx = nm[0], my = nm[1], mz = nm[2];
    uint8_t g = s_vgroup[t->v[0]];
    if (scan && (g == 1 || g == 2)) rot_apply(&rot, &mx, &my, &mz);
    if (s_roll_on) {
      int32_t lx = (mx * s_roll_c - my * s_roll_s) / TRIG_MAX_RATIO;
      my = (mx * s_roll_s + my * s_roll_c) / TRIG_MAX_RATIO;
      mx = lx;
    }
    // rotate the normal by the same yaw as the vertices
    int32_t nx = (mx * yc + mz * ys) / TRIG_MAX_RATIO;
    int32_t nz = (-mx * ys + mz * yc) / TRIG_MAX_RATIO;
    int32_t ny = my;
    if (nz < 0) {  // a two-sided face seen from behind: light its back
      nx = -nx; ny = -ny; nz = -nz;
    }
    const uint8_t *pat = shade(t->col, nx, ny, nz);
    raster_tri(fb, fb_h, &s_sv[t->v[0]], &s_sv[t->v[1]], &s_sv[t->v[2]], pat, true);
  }
}

// ---------------------------------------------------------------------------
// The eye

#define RING_SEGS 40
#define WEDGES 24

// annulus between two radii (x1000); r0 = 0 gives a disc
static int s_ring_segs = RING_SEGS;  // fewer when the eye is small

static void fill_ring(GBitmap *fb, int fb_h, int32_t r0, int32_t r1, const uint8_t pat[16]) {
  ScreenVert c, pi0, po0, pi1, po1;
  const int segs = s_ring_segs;
  eye_pt(0, 0, &c);
  eye_pt(0, r0, &pi0);
  eye_pt(0, r1, &po0);
  for (int i = 1; i <= segs; i++) {
    int32_t a = i * TRIG_MAX_ANGLE / segs;
    eye_pt(a, r1, &po1);
    if (r0 == 0) {
      raster_tri(fb, fb_h, &c, &po0, &po1, pat, false);
    } else {
      eye_pt(a, r0, &pi1);
      raster_tri(fb, fb_h, &pi0, &po0, &po1, pat, false);
      raster_tri(fb, fb_h, &pi0, &po1, &pi1, pat, false);
      pi0 = pi1;
    }
    po0 = po1;
  }
}

static void fill_wedge(GBitmap *fb, int fb_h, int32_t angle, int32_t half,
                       int32_t r0, int32_t r1, const uint8_t pat[16]) {
  ScreenVert p[4];
  eye_pt(angle - half, r0, &p[0]);
  eye_pt(angle - half, r1, &p[1]);
  eye_pt(angle + half, r1, &p[2]);
  eye_pt(angle + half, r0, &p[3]);
  raster_tri(fb, fb_h, &p[0], &p[1], &p[2], pat, false);
  raster_tri(fb, fb_h, &p[0], &p[2], &p[3], pat, false);
}

static void solid(GColor c, uint8_t pat[16]) {
  memset(pat, c.argb, 16);
}

static void render_eye(GBitmap *fb) {
  int fb_h = gbitmap_get_bounds(fb).size.h;
  uint8_t pat[16];
  float r_px = s_hdr.eye_r * s_cam.scale;
  // zoomed out the eye is only a few pixels across: far fewer triangles
  bool small = r_px < 24.0f;
  s_ring_segs = small ? 16 : RING_SEGS;

  if (r_px < 6.0f) {
    // far away: just the glowing lens
    solid(GColorBlack, pat);
    fill_ring(fb, fb_h, 0, 1000, pat);
    solid(GColorRed, pat);
    fill_ring(fb, fb_h, 340, 880, pat);
    return;
  }

  // housing: bevelled rim, dark socket, black lens bezel
  solid(GColorLightGray, pat);
  fill_ring(fb, fb_h, 1160, EYE_OUTER, pat);
  solid(GColorDarkGray, pat);
  fill_ring(fb, fb_h, 1000, 1160, pat);
  solid(GColorBlack, pat);
  fill_ring(fb, fb_h, 0, 1000, pat);

  // 24 radial wedges, darkening towards the rim like the real lens. The
  // wedge nearest the minute hand glows along its whole length; the one
  // nearest the hour hand glows only on its inner half.
  int hour_wedge = (((s_now.tm_hour % 12) * 60 + s_now.tm_min) * WEDGES + 360) / 720 % WEDGES;
  int32_t half = TRIG_MAX_ANGLE / WEDGES * 30 / 100;  // 60% wedge, 40% gap
  int min_wedge = (s_now.tm_min * WEDGES + 30) / 60 % WEDGES;
  uint8_t dim[4][16], hot[4][16];
  mix_pattern(GColorBulgarianRose, GColorDarkCandyAppleRed, 13, dim[0]);
  mix_pattern(GColorBulgarianRose, GColorDarkCandyAppleRed, 9, dim[1]);
  mix_pattern(GColorBulgarianRose, GColorDarkCandyAppleRed, 4, dim[2]);
  mix_pattern(GColorBlack, GColorBulgarianRose, 10, dim[3]);
  mix_pattern(GColorRed, GColorOrange, 6, hot[0]);
  solid(GColorRed, hot[1]);
  solid(GColorRed, hot[2]);
  mix_pattern(GColorDarkCandyAppleRed, GColorRed, 12, hot[3]);
  static const int16_t RINGS[5] = { 340, 480, 620, 760, 900 };
  int step = small ? 2 : 1;  // small: two bands (inner/outer half) per wedge
  for (int i = 0; i < WEDGES; i++) {
    int32_t angle = i * TRIG_MAX_ANGLE / WEDGES;
    for (int r = 0; r < 4; r += step) {
      bool lit = i == min_wedge || (i == hour_wedge && r < 2);
      fill_wedge(fb, fb_h, angle, half, RINGS[r], RINGS[r + step], lit ? hot[r + step - 1] : dim[r]);
    }
  }
}

// ---------------------------------------------------------------------------
// Test chamber backdrop: a panelled back wall and a tiled floor the turret
// stands on, drawn through the same camera before the turret so it gets
// perspective and sways with it. Each wall panel and floor tile is white or
// near-black, chosen on the phone (see Settings). Sizes in model units (the
// turret is ~1.75 tall, its feet at y = 0).

#define WALL_Z (-1.25f)
#define WALL_PANEL 0.9f
#define FLOOR_TILE 0.45f
#define FLOOR_NEAR 1.6f

static void room_quad(GBitmap *fb, int fb_h, int32_t q[4][3], const uint8_t pat[16]) {
  ScreenVert sv[4];
  for (int i = 0; i < 4; i++) {
    int32_t x = q[i][0], z = q[i][2];
    yaw_q(&x, &z);
    project(x, q[i][1], z, &sv[i]);
  }
  raster_tri(fb, fb_h, &sv[0], &sv[1], &sv[2], pat, true);
  raster_tri(fb, fb_h, &sv[0], &sv[2], &sv[3], pat, true);
}

// A grid of panels on the wall (a = x, b = y) or the floor (a = x, b = z)
typedef struct {
  bool floor;
  int32_t z;                 // wall plane
  int32_t a0, b0, cell, b_end;
  int cols, rows, base;      // tiles base .. base + cols * rows in the room bits
  const uint8_t *light, *dark;
  uint8_t seam_l, seam_d;    // seam colours between two light / two dark tiles
} Grid;

static void grid_quad(GBitmap *fb, int fb_h, const Grid *g, int32_t a0, int32_t b0,
                      int32_t a1, int32_t b1, const uint8_t *pat) {
  int32_t q[4][3];
  if (g->floor) {
    int32_t f[4][3] = { { a0, 0, b0 }, { a1, 0, b0 }, { a1, 0, b1 }, { a0, 0, b1 } };
    memcpy(q, f, sizeof(q));
  } else {
    int32_t w[4][3] = { { a0, b0, g->z }, { a1, b0, g->z }, { a1, b1, g->z }, { a0, b1, g->z } };
    memcpy(q, w, sizeof(q));
  }
  room_quad(fb, fb_h, q, pat);
}

// a room point on the grid, projected
static void grid_point(const Grid *g, int32_t a, int32_t b, ScreenVert *out) {
  int32_t x = a, y = g->floor ? 0 : b, z = g->floor ? b : g->z;
  yaw_q(&x, &z);
  project(x, y, z, out);
}

// A 1-pixel line (Bresenham), clipped to the screen. Seams are drawn this way
// rather than as thin quads: a strip narrower than a pixel flickers between
// showing and not as the camera moves; a line is always exactly one pixel.
static void seam_line(int fb_h, const ScreenVert *p0, const ScreenVert *p1, uint8_t color) {
  float x0 = p0->x / 256.0f, y0 = p0->y / 256.0f, x1 = p1->x / 256.0f, y1 = p1->y / 256.0f;
  // clip to [0, w) x [0, h) (Liang-Barsky)
  float w = MAX_ROWS, h = fb_h;  // width: rows are at most MAX_ROWS wide
  float t0 = 0, t1 = 1, dx = x1 - x0, dy = y1 - y0;
  float pp[4] = { -dx, dx, -dy, dy }, qq[4] = { x0, w - 1 - x0, y0, h - 1 - y0 };
  for (int i = 0; i < 4; i++) {
    if (pp[i] == 0) {
      if (qq[i] < 0) return;
    } else {
      float t = qq[i] / pp[i];
      if (pp[i] < 0) { if (t > t1) return; if (t > t0) t0 = t; }
      else { if (t < t0) return; if (t < t1) t1 = t; }
    }
  }
  int32_t ax = (int32_t)(x0 + t0 * dx), ay = (int32_t)(y0 + t0 * dy);
  int32_t bx = (int32_t)(x0 + t1 * dx), by = (int32_t)(y0 + t1 * dy);
  int32_t ddx = bx > ax ? bx - ax : ax - bx, ddy = by > ay ? by - ay : ay - by;
  int32_t sx = ax < bx ? 1 : -1, sy = ay < by ? 1 : -1;
  int32_t err = ddx - ddy;
  for (;;) {
    if (ay >= 0 && ay < fb_h && ax >= s_row_min[ay] && ax <= s_row_max[ay]) {
      s_row_data[ay][ax] = color;
    }
    if (ax == bx && ay == by) break;
    int32_t e2 = 2 * err;
    if (e2 > -ddy) { err -= ddy; ax += sx; }
    if (e2 < ddx) { err += ddx; ay += sy; }
  }
}

static void grid_line(int fb_h, const Grid *g, int32_t a0, int32_t b0, int32_t a1, int32_t b1,
                      uint8_t color) {
  ScreenVert p, q;
  grid_point(g, a0, b0, &p);
  grid_point(g, a1, b1, &q);
  seam_line(fb_h, &p, &q, color);
}

// The grid is drawn at half-tile resolution: column sc, row sr of the quarter
// cells. Whole tiles simply have four quarters of the same colour.
static inline uint8_t grid_tile(const Grid *g, int sc, int sr) {
  return s_cfg.room[g->base + (sr >> 1) * g->cols + (sc >> 1)];
}

static inline bool grid_dark(const Grid *g, int sc, int sr) {
  return (grid_tile(g, sc, sr) >> ((sc & 1) + 2 * (sr & 1))) & 1;
}

static inline int32_t grid_a(const Grid *g, int sc) { return g->a0 + sc * (g->cell / 2); }
static inline int32_t grid_b(const Grid *g, int sr) {
  int32_t b = g->b0 + sr * (g->cell / 2);
  return b < g->b_end ? b : g->b_end;
}

// is there a seam between quarter columns sc - 1 and sc in quarter row sr
// (between tiles always, inside a tile only when it is split)?
static inline bool vseam(const Grid *g, int sc, int sr) {
  return !(sc & 1) || (grid_tile(g, sc, sr) & TILE_SPLIT);
}

static inline bool hseam(const Grid *g, int sc, int sr) {
  return !(sr & 1) || (grid_tile(g, sc, sr) & TILE_SPLIT);
}

// Tiles go down as runs of the same colour, then 1-pixel seams on top: grey
// between two light tiles, black between two dark ones, and none where light
// meets dark (the change of colour is the edge there).
static void render_grid(GBitmap *fb, int fb_h, const Grid *g) {
  int nc = g->cols * 2, nr = g->rows * 2;
  for (int r = 0; r < nr; r++) {
    int32_t b0 = grid_b(g, r), b1 = grid_b(g, r + 1);
    for (int c = 0; c < nc;) {
      bool d = grid_dark(g, c, r);
      int e = c + 1;
      while (e < nc && grid_dark(g, e, r) == d) e++;
      grid_quad(fb, fb_h, g, grid_a(g, c), b0, grid_a(g, e), b1, d ? g->dark : g->light);
      c = e;
    }
  }
  // seam kind: 0 = none, 1 = light, 2 = dark
  #define KIND(d0, d1) ((d0) == (d1) ? 1 + (d0) : 0)
  #define VSEAM(c, r) (vseam(g, c, r) ? KIND(grid_dark(g, (c) - 1, r), grid_dark(g, c, r)) : 0)
  #define HSEAM(c, r) (hseam(g, c, r) ? KIND(grid_dark(g, c, (r) - 1), grid_dark(g, c, r)) : 0)
  for (int c = 1; c < nc; c++) {  // seams between columns
    for (int r = 0; r < nr;) {
      int k = VSEAM(c, r);
      int e = r + 1;
      while (e < nr && VSEAM(c, e) == k) e++;
      if (k) {
        grid_line(fb_h, g, grid_a(g, c), grid_b(g, r), grid_a(g, c), grid_b(g, e),
                  k == 2 ? g->seam_d : g->seam_l);
      }
      r = e;
    }
  }
  for (int r = 1; r < nr; r++) {  // seams between rows
    for (int c = 0; c < nc;) {
      int k = HSEAM(c, r);
      int e = c + 1;
      while (e < nc && HSEAM(e, r) == k) e++;
      if (k) {
        grid_line(fb_h, g, grid_a(g, c), grid_b(g, r), grid_a(g, e), grid_b(g, r),
                  k == 2 ? g->seam_d : g->seam_l);
      }
      c = e;
    }
  }
  #undef VSEAM
  #undef HSEAM
}


static void render_room(GBitmap *fb) {
  int fb_h = gbitmap_get_bounds(fb).size.h;
  float iv = 1.0f / s_hdr.vscale;
  int32_t panel = (int32_t)(WALL_PANEL * iv);
  int32_t tile = (int32_t)(FLOOR_TILE * iv);
  int32_t wx0 = -(WALL_COLS / 2) * panel - panel / 2;

  uint8_t pan_l[16], pan_d[16], fl_l[16], fl_d[16];
  mix_pattern(GColorLightGray, GColorWhite, 3, pan_l);
  mix_pattern(GColorBlack, GColorDarkGray, 4, pan_d);
  mix_pattern(GColorLightGray, GColorWhite, 11, fl_l);
  mix_pattern(GColorBlack, GColorDarkGray, 7, fl_d);

  Grid wall = {
    .floor = false, .z = (int32_t)(WALL_Z * iv),
    .a0 = wx0, .b0 = 0, .cell = panel, .b_end = WALL_ROWS * panel,
    .cols = WALL_COLS, .rows = WALL_ROWS, .base = 0,
    .light = pan_l, .dark = pan_d,
    .seam_l = GColorDarkGrayARGB8, .seam_d = GColorBlackARGB8,
  };
  render_grid(fb, fb_h, &wall);

  Grid floor = {
    .floor = true,
    .a0 = wx0, .b0 = wall.z, .cell = tile, .b_end = (int32_t)(FLOOR_NEAR * iv),
    .cols = FLOOR_COLS, .rows = FLOOR_ROWS, .base = WALL_COLS * WALL_ROWS,
    .light = fl_l, .dark = fl_d,
    .seam_l = GColorLightGrayARGB8, .seam_d = GColorBlackARGB8,
  };
  render_grid(fb, fb_h, &floor);

  // where the wall meets the floor, by floor quarter (a wall quarter is two
  // floor quarters wide), with the same rule as the seams
  for (int c = 0; c < FLOOR_COLS * 2;) {
    #define SKIRT(c) KIND_(grid_dark(&wall, (c) >> 1, 0), grid_dark(&floor, c, 0))
    #define KIND_(d0, d1) ((d0) == (d1) ? 1 + (d0) : 0)
    int k = SKIRT(c);
    int e = c + 1;
    while (e < FLOOR_COLS * 2 && SKIRT(e) == k) e++;
    if (k) {
      grid_line(fb_h, &floor, grid_a(&floor, c), floor.b0, grid_a(&floor, e), floor.b0,
                k == 2 ? wall.seam_d : wall.seam_l);
    }
    #undef SKIRT
    #undef KIND_
    c = e;
  }
}

// ---------------------------------------------------------------------------
// Laser sight: a red beam from the eye along the scan direction, ending in a
// dot where it meets the floor.

// a screen-space strip of width w (24.8) from a to b
static void beam(GBitmap *fb, int fb_h, const ScreenVert *a, const ScreenVert *b,
                 int32_t w, const uint8_t pat[16]) {
  int32_t dx = b->x - a->x, dy = b->y - a->y;
  int32_t len = (int32_t)isqrt((uint32_t)(((int64_t)dx * dx + (int64_t)dy * dy) >> 8)) << 4;
  if (len < 1) return;
  int32_t px = (int32_t)((int64_t)-dy * w / 2 / len), py = (int32_t)((int64_t)dx * w / 2 / len);
  ScreenVert q[4] = {
    { a->x + px, a->y + py, 0 }, { b->x + px, b->y + py, 0 },
    { b->x - px, b->y - py, 0 }, { a->x - px, a->y - py, 0 },
  };
  raster_tri(fb, fb_h, &q[0], &q[1], &q[2], pat, false);
  raster_tri(fb, fb_h, &q[0], &q[2], &q[3], pat, false);
}

static void render_laser(GBitmap *fb) {
  int fb_h = gbitmap_get_bounds(fb).size.h;
  float iv = 1.0f / s_hdr.vscale;
  int32_t yaw, pitch;
  scan_angles(&yaw, &pitch);
  Rot r;
  rot_make(&r, yaw, pitch + LASER_TILT);
  int32_t dx = 0, dy = 0, dz = 1 << 12;  // straight ahead, 1.0 in .12
  rot_apply(&r, &dx, &dy, &dz);
  if (s_roll_on) {
    int32_t lx = (int32_t)(((int64_t)dx * s_roll_c - (int64_t)dy * s_roll_s) >> 16);
    dy = (int32_t)(((int64_t)dx * s_roll_s + (int64_t)dy * s_roll_c) >> 16);
    dx = lx;
  }

  int32_t ex = (int32_t)(s_hdr.eye[0] * iv), ey = (int32_t)(s_hdr.eye[1] * iv);
  int32_t ez = (int32_t)(s_hdr.eye[2] * iv);
  roll_q(&ex, &ey);
  int32_t len = (int32_t)(LASER_LEN * iv);
  bool hit = false;
  if (dy < 0) {
    int32_t to_floor = (int32_t)((int64_t)ey * (1 << 12) / -dy);
    if (to_floor < len) { len = to_floor; hit = true; }
  }
  int32_t x1 = ex + (int32_t)(((int64_t)dx * len) >> 12);
  int32_t y1 = ey + (int32_t)(((int64_t)dy * len) >> 12);
  int32_t z1 = ez + (int32_t)(((int64_t)dz * len) >> 12);
  yaw_q(&ex, &ez);
  yaw_q(&x1, &z1);
  ScreenVert a, b;
  project(ex, ey, ez, &a);
  project(x1, y1, z1, &b);
  uint8_t glow[16], core[16];
  solid(GColorBulgarianRose, glow);
  solid(GColorDarkCandyAppleRed, core);
  beam(fb, fb_h, &a, &b, 3 * 256, glow);
  beam(fb, fb_h, &a, &b, 256 + 128, core);
  if (hit) {
    ScreenVert d0 = { b.x - 512, b.y, 0 }, d1 = { b.x + 512, b.y, 0 };
    beam(fb, fb_h, &d0, &d1, 3 * 256, core);
  }
}

// ---------------------------------------------------------------------------

static void schedule_frame(void);
static uint32_t s_draw_ms;  // how long the last frame took to draw

static void canvas_update(Layer *layer, GContext *ctx) {
  uint64_t t0 = now_ms();
  GRect bounds = layer_get_bounds(layer);
  graphics_context_set_fill_color(ctx, GColorBlack);
  graphics_fill_rect(ctx, bounds, 0, GCornerNone);
  if (!s_hdr_ok) return;

// Freeze a pose for screenshots: build with DEBUG_POSE/ZOOM/WING/SWAY defined
#ifdef DEBUG_POSE
  s_zoom_p = DEBUG_ZOOM;
  s_wing_p = DEBUG_WING;
  s_sway_ms = DEBUG_SWAY;
#ifdef DEBUG_SCAN
  s_scan_p = 1000;
  s_scan_ms = DEBUG_SCAN;
#endif
#ifdef DEBUG_TIP
  s_tip_ms = DEBUG_TIP;
  s_tip_dir = 1;
#endif
#endif
  float zoom = ease(s_zoom_p);
  float wings = s_out ? (s_wing_p >= 1000 ? 1.0f : ease_back_out(s_wing_p))
                      : ease(s_wing_p);  // no overshoot when closing

  setup_roll();
  setup_camera(bounds, zoom);
  bool have_model = ensure_model();

  GBitmap *fb = graphics_capture_frame_buffer(ctx);
  if (fb) {
    cache_rows(fb);
    setup_mask(gbitmap_get_bounds(fb).size.h);
    render_room(fb);
    audio_pump();
    if (have_model) render_model(fb, bounds, wings);
    render_eye(fb);
    if (s_wing_p == 1000) render_laser(fb);
    graphics_release_frame_buffer(ctx, fb);
  }

  // the time, small, printed on the bottom of the eye's grey housing ring;
  // it rides along with the ring and disappears as the eye shrinks
  if (s_cfg.show_time && s_hdr.eye_r * s_cam.scale > EYE_PX * 0.75f) {
    ScreenVert lp;
    eye_pt(TRIG_MAX_ANGLE / 2, 1080, &lp);
    int16_t x = (int16_t)(lp.x >> 8), y = (int16_t)(lp.y >> 8);
    graphics_context_set_text_color(ctx, GColorBlack);
    graphics_draw_text(ctx, s_time_buf, s_font, GRect(x - 30, y - 10, 60, 18),
                       GTextOverflowModeFill, GTextAlignmentCenter, NULL);
  }

  // between animations the mesh doesn't need to stay in RAM
  if (!animating()) release_model();

  int64_t took = (int64_t)(now_ms() - t0);
  s_draw_ms = took < 0 ? 0 : took > 500 ? 500 : (uint32_t)took;
  if (animating()) schedule_frame();
#ifdef STORE_CAPTURE
  APP_LOG(APP_LOG_LEVEL_INFO, animating() || !s_cap_frame ? "GIF %d" : "GIF END %d", s_cap_frame);
#endif
}

static void step(int32_t *p, int32_t target, int32_t dt, int32_t dur) {
  int32_t d = dt * 1000 / dur;
  if (*p < target) { *p += d; if (*p > target) *p = target; }
  else if (*p > target) { *p -= d; if (*p < target) *p = target; }
}

// the animation's clock
static uint64_t anim_ms(void) {
#ifdef STORE_CAPTURE
  return s_cap_clock;
#else
  return now_ms();
#endif
}

static void frame_cb(void *data) {
  s_timer = NULL;
  audio_pump();
#ifdef STORE_CAPTURE
  int32_t dt = CAPTURE_DT_MS;
  s_cap_clock += dt;
  s_cap_frame++;
  uint64_t now = s_cap_clock;
#else
  uint64_t now = now_ms();
  int32_t dt = (int32_t)(now - s_last_ms);
  s_last_ms = now;
  // time_ms() can step backwards when the seconds and millis disagree
  if (dt <= 0) dt = FRAME_MS;
  if (dt > 150) dt = 150;
#endif

  if (s_zoom_p > 0) s_sway_ms += dt;

  if (s_scan_p > 0) s_scan_ms += dt;
  if (s_tip_ms < TIP_MS) s_tip_ms += dt;

  if (s_out) {
    step(&s_zoom_p, 1000, dt, ZOOM_MS);
    if (s_zoom_p > 750) {
      if (s_wing_p == 0) {
        audio_play(AUDIO_CH_SFX, VOICE_SFX_DEPLOY);
        if (s_tip_ms >= TIP_MS) {
          // the panels kicking out rock it onto one foot
          s_tip_ms = 0;
#ifdef STORE_CAPTURE
          s_tip_dir = 1;
#else
          s_tip_dir = (rand() & 1) ? 1 : -1;
#endif
        }
      }
      step(&s_wing_p, 1000, dt, WINGS_MS);
    }
    if (s_wing_p == 1000) step(&s_scan_p, 1000, dt, SCAN_RAMP_MS);
    if (s_zoom_p == 1000 && s_wing_p == 1000 && now >= s_hold_until) {
      s_out = false;
      audio_play_random(AUDIO_CH_VOICE, VOICE_RETIRE_FIRST, VOICE_RETIRE_COUNT);
      audio_play(AUDIO_CH_SFX, VOICE_SFX_RETRACT);
    }
  } else {
    // stop scanning and face forward before the panels fold away
    step(&s_scan_p, 0, dt, SCAN_RAMP_MS);
    if (s_scan_p == 0) {
      s_scan_ms = 0;
      step(&s_wing_p, 0, dt, WINGS_MS);
    }
    if (s_wing_p < 300) step(&s_zoom_p, 0, dt, ZOOM_MS);
  }
  if (!animating()) s_sway_ms = 0;
#if 0  // timing log for tuning the audio duty cycle
  static int s_nframe;
  if (++s_nframe % 10 == 0) {
    APP_LOG(APP_LOG_LEVEL_INFO, "frame draw=%lu ms dt=%ld audio=%d", (unsigned long)s_draw_ms,
            (long)dt, (int)audio_busy());
  }
#endif
  layer_mark_dirty(s_canvas);  // the redraw schedules the next frame
}

// The next frame is timed from the end of this one's drawing. While sound
// is playing the CPU is left idle 1.5x as long as it spent drawing:
// the speaker is fed in the background, and a watch kept 100% busy plays the
// stream back far slower than real time.
static void schedule_frame(void) {
  if (s_timer) return;
#ifdef STORE_CAPTURE
  s_timer = app_timer_register(CAPTURE_FRAME_MS, frame_cb, NULL);
  return;
#endif
  int32_t wait = FRAME_MS - (int32_t)s_draw_ms;
  if (audio_busy() && wait < (int32_t)s_draw_ms * 3 / 2) wait = s_draw_ms * 3 / 2;
  if (wait < 10) wait = 10;
  s_timer = app_timer_register(wait, frame_cb, NULL);
}

static void tap_handler(AccelAxisType axis, int32_t direction) {
  if (!s_out) audio_play_random(AUDIO_CH_VOICE, VOICE_DEPLOY_FIRST, VOICE_DEPLOY_COUNT);
  s_out = true;
  s_hold_until = anim_ms() + HOLD_MS;
  if (!s_timer) {
    s_last_ms = now_ms();
    schedule_frame();
  }
}

static void update_time(struct tm *t) {
  s_now = *t;
#ifdef STORE_TIME
  s_now.tm_hour = 10;  // the classic watch-ad time
  s_now.tm_min = 8;
#endif
  strftime(s_time_buf, sizeof(s_time_buf), clock_is_24h_style() ? "%H:%M" : "%I:%M", &s_now);
}

static void tick_handler(struct tm *tick_time, TimeUnits changed) {
  update_time(tick_time);
  layer_mark_dirty(s_canvas);
}

// ---------------------------------------------------------------------------

static void window_load(Window *window) {
  Layer *root = window_get_root_layer(window);
  s_canvas = layer_create(layer_get_bounds(root));
  layer_set_update_proc(s_canvas, canvas_update);
  layer_add_child(root, s_canvas);
}

static void window_unload(Window *window) {
  layer_destroy(s_canvas);
}

static void inbox_received(DictionaryIterator *iter, void *context) {
  Tuple *t;
  if ((t = dict_find(iter, MESSAGE_KEY_SHOW_TIME))) s_cfg.show_time = t->value->int32 != 0;
  if ((t = dict_find(iter, MESSAGE_KEY_VOLUME))) {
    int32_t v = t->value->int32;
    s_cfg.volume = v < 0 ? 0 : v > 100 ? 100 : v;
    audio_set_volume(s_cfg.volume);
  }
  if ((t = dict_find(iter, MESSAGE_KEY_ROOM)) && t->type == TUPLE_BYTE_ARRAY
      && t->length == ROOM_TILES) {
    memcpy(s_cfg.room, t->value->data, ROOM_TILES);
  }
  persist_write_data(SETTINGS_KEY, &s_cfg, sizeof(s_cfg));
  layer_mark_dirty(s_canvas);
}

static void init(void) {
  srand(time(NULL));
  load_settings();
  load_header();
  s_font = fonts_get_system_font(FONT_KEY_GOTHIC_14_BOLD);
  time_t t = time(NULL);
  update_time(localtime(&t));

  s_window = window_create();
  window_set_background_color(s_window, GColorBlack);
  window_set_window_handlers(s_window, (WindowHandlers) {
    .load = window_load,
    .unload = window_unload,
  });
  window_stack_push(s_window, false);
#ifdef STORE_CAPTURE
  app_timer_register(CAPTURE_FRAME_MS, (AppTimerCallback)tap_handler, NULL);
#endif

  tick_timer_service_subscribe(MINUTE_UNIT, tick_handler);
  app_message_register_inbox_received(inbox_received);
  app_message_open(256, 16);
  accel_tap_service_subscribe(tap_handler);
}

static void deinit(void) {
  audio_deinit();
  accel_tap_service_unsubscribe();
  tick_timer_service_unsubscribe();
  if (s_timer) app_timer_cancel(s_timer);
  window_destroy(s_window);
  release_model();
}

int main(void) {
  init();
  app_event_loop();
  deinit();
}
