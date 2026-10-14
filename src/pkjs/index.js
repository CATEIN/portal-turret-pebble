// Phone side: the settings page, and sending its choices to the watch, which
// keeps them in persistent storage (see Settings in src/c/main.c).

var settingsPage = require('./settings_page');
var view = require('./turret_view');

var SETTINGS_KEY = 'settings2';
var OLD_SETTINGS_KEY = 'settings';  // a 0/1 per tile, before tiles could split
var WALL_COLS = 8, WALL_ROWS = 4, FLOOR_COLS = 16, FLOOR_ROWS = 7;
var ROOM_TILES = WALL_COLS * WALL_ROWS + FLOOR_COLS * FLOOR_ROWS;

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
  for (r = 0; r < 2; r++) {
    for (c = 10; c < FLOOR_COLS; c++) room[WALL_COLS * WALL_ROWS + r * FLOOR_COLS + c] = TILE_DARK;
  }
  return room;
}

function settings() {
  var s = { showTime: true, volume: 70, room: defaultRoom() };
  try {
    var saved = JSON.parse(localStorage.getItem(SETTINGS_KEY));
    var old = !saved;
    if (old) saved = JSON.parse(localStorage.getItem(OLD_SETTINGS_KEY));
    if (saved) {
      if (typeof saved.showTime === 'boolean') s.showTime = saved.showTime;
      if (typeof saved.volume === 'number') s.volume = saved.volume;
      if (saved.room && saved.room.length === ROOM_TILES) {
        s.room = saved.room.map(function (v) { return old ? (v ? TILE_DARK : 0) : v & 0x1F; });
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
    volume: Math.max(0, Math.min(100, Math.round(+s.volume || 0))),
    room: (s.room && s.room.length === ROOM_TILES) ? s.room.map(function (v) { return (v | 0) & 0x1F; })
                                                   : defaultRoom()
  };
  localStorage.setItem(SETTINGS_KEY, JSON.stringify(clean));
  Pebble.sendAppMessage({
    SHOW_TIME: clean.showTime ? 1 : 0,
    VOLUME: clean.volume,
    ROOM: clean.room
  }, function () {}, function () {
    console.log('Failed to send settings');
  });
});
