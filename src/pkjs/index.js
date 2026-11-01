// Phone side: the settings page, and sending its choices to the watch, which
// keeps them in persistent storage (see Settings in src/c/main.c).

var settingsPage = require('./settings_page');
var view = require('./turret_view');
var keys = require('message_keys');

// Portal Turret Lite has no defective turret: it leaves out its settings
// (and their message keys, see lite/package.json)
var LITE = keys.DEFECT_CHANCE === undefined;

var SETTINGS_KEY = 'settings2';
var OLD_SETTINGS_KEY = 'settings';  // a 0/1 per tile, before tiles could split
var WALL_COLS = 8, WALL_ROWS = 4, FLOOR_COLS = 8, FLOOR_ROWS = 4;
var ROOM_TILES = WALL_COLS * WALL_ROWS + FLOOR_COLS * FLOOR_ROWS;
// before 1.2 the floor tiles were half a wall panel, 16 x 7 of them
var FLOOR_COLS_OLD = 16, FLOOR_ROWS_OLD = 7;
var ROOM_TILES_OLD = WALL_COLS * WALL_ROWS + FLOOR_COLS_OLD * FLOOR_ROWS_OLD;

// A number per tile, as on the watch: bits 0-3 say which quarters are dark
// (x half + 2 * row half), TILE_SPLIT that it shows as four small tiles.
var TILE_SPLIT = 0x10, TILE_DARK = 0x0F;

// matches default_settings() on the watch: the right part of the wall and
// the floor strip in front of it are dark
function defaultRoom() {
  var room = [];
  for (var i = 0; i < ROOM_TILES; i++) room.push(0);
  var r, c;
  for (r = 0; r < WALL_ROWS; r++) {
    for (c = 5; c < WALL_COLS; c++) room[r * WALL_COLS + c] = TILE_DARK;
  }
  for (c = 5; c < FLOOR_COLS; c++) room[WALL_COLS * WALL_ROWS + c] = TILE_DARK;
  return room;
}

// a room saved before 1.2, as on the watch (room_from_old): each floor tile
// takes the four small tiles it now covers as its quarters
function roomFromOld(old) {
  var room = old.slice(0, WALL_COLS * WALL_ROWS);
  function dark(c, r) {
    var q = old[WALL_COLS * WALL_ROWS + r * FLOOR_COLS_OLD + c] & TILE_DARK;
    return (q & 1) + ((q >> 1) & 1) + ((q >> 2) & 1) + ((q >> 3) & 1) >= 2;
  }
  for (var r = 0; r < FLOOR_ROWS; r++) {
    for (var c = 0; c < FLOOR_COLS; c++) {
      var v = 0;
      for (var q = 0; q < 4; q++) {
        if (dark(2 * c + (q & 1), Math.min(2 * r + (q >> 1), FLOOR_ROWS_OLD - 1))) v |= 1 << q;
      }
      if (v !== 0 && v !== TILE_DARK) v |= TILE_SPLIT;
      room.push(v);
    }
  }
  return room;
}

function settings() {
  var s = { showTime: true, dial24: false, volume: 70, seeChance: 25, defectChance: 15, explodeChance: 100, fireChance: 50,
            room: defaultRoom() };
  try {
    var saved = JSON.parse(localStorage.getItem(SETTINGS_KEY));
    var old = !saved;
    if (old) saved = JSON.parse(localStorage.getItem(OLD_SETTINGS_KEY));
    if (saved) {
      if (typeof saved.showTime === 'boolean') s.showTime = saved.showTime;
      if (typeof saved.dial24 === 'boolean') s.dial24 = saved.dial24;
      if (typeof saved.volume === 'number') s.volume = saved.volume;
      if (typeof saved.seeChance === 'number') s.seeChance = saved.seeChance;
      if (typeof saved.defectChance === 'number') s.defectChance = saved.defectChance;
      if (typeof saved.explodeChance === 'number') s.explodeChance = saved.explodeChance;
      if (typeof saved.fireChance === 'number') s.fireChance = saved.fireChance;
      if (saved.room && (saved.room.length === ROOM_TILES || saved.room.length === ROOM_TILES_OLD)) {
        var room = saved.room.map(function (v) { return old ? (v ? TILE_DARK : 0) : v & 0x1F; });
        s.room = room.length === ROOM_TILES_OLD ? roomFromOld(room) : room;
      }
    }
  } catch (e) {
    // keep the defaults
  }
  return s;
}

Pebble.addEventListener('showConfiguration', function () {
  var s = settings();
  s.defaultRoom = defaultRoom();
  s.lite = LITE;
  Pebble.openURL('data:text/html;charset=utf-8,' + encodeURIComponent(settingsPage(s, view)));
});

Pebble.addEventListener('webviewclosed', function (e) {
  if (!e || !e.response) return;  // closed without saving
  var s;
  try {
    s = JSON.parse(decodeURIComponent(e.response));
  } catch (err) {
    console.log('Bad settings from the page: ' + err);
    return;
  }
  var clean = {
    showTime: !!s.showTime,
    dial24: !!s.dial24,
    volume: Math.max(0, Math.min(100, Math.round(+s.volume || 0))),
    seeChance: Math.max(0, Math.min(100, Math.round(+s.seeChance || 0))),
    defectChance: Math.max(0, Math.min(100, Math.round(+s.defectChance || 0))),
    explodeChance: Math.max(0, Math.min(100, Math.round(+s.explodeChance || 0))),
    fireChance: Math.max(0, Math.min(100, Math.round(+s.fireChance || 0))),
    room: (s.room && s.room.length === ROOM_TILES) ? s.room.map(function (v) { return (v | 0) & 0x1F; })
                                                   : defaultRoom()
  };
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(clean));
  var msg = {
    SHOW_TIME: clean.showTime ? 1 : 0,
    DIAL_24: clean.dial24 ? 1 : 0,
    VOLUME: clean.volume,
    SEE_CHANCE: clean.seeChance,
    ROOM: clean.room
  };
  if (!LITE) {
    msg.DEFECT_CHANCE = clean.defectChance;
    msg.EXPLODE_CHANCE = clean.explodeChance;
    msg.FIRE_CHANCE = clean.fireChance;
  }
  Pebble.sendAppMessage(msg, function () {}, function () {
    console.log('Failed to send settings');
  });
});
