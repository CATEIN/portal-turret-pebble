// The phone settings page, opened as a data: URL from showConfiguration.
// It returns its result through pebblejs://close# as JSON:
//   { showTime: bool, volume: 0..100, room: [bit per tile, 1 = dark] }
//
// The room is drawn with the same camera as the watch's zoomed-out view
// (tools/render_view.py), so the tiles line up with what the watch shows.

var CSS = [
  ':root{--bg:#f2f2f2;--card:#fff;--text:#1c1c1c;--muted:#777;--line:#e4e4e4;--accent:#ff6a00;color-scheme:light dark}',
  '@media (prefers-color-scheme:dark){:root{--bg:#121212;--card:#1e1e1e;--text:#f0f0f0;--muted:#9a9a9a;--line:#2c2c2c;--accent:#ff8a2a}}',
  '*{box-sizing:border-box}',
  'html,body{margin:0;background:var(--bg);color:var(--text)}',
  'body{font:16px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;padding:20px 16px 100px;max-width:480px;margin:0 auto;-webkit-text-size-adjust:100%}',
  'h1{font-size:22px;margin:4px 4px 2px}',
  '.sub{color:var(--muted);margin:0 4px 20px;font-size:14px}',
  'h2{font-size:13px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);margin:0 4px 8px}',
  '.card{background:var(--card);border-radius:14px;padding:16px;margin-bottom:24px}',
  '.row{display:flex;align-items:center;justify-content:space-between;gap:12px}',
  '.hint{color:var(--muted);font-size:13px;margin:8px 0 0}',
  'input[type=checkbox]{width:22px;height:22px;accent-color:var(--accent)}',
  'input[type=range]{width:100%;accent-color:var(--accent);margin:12px 0 0}',
  '#vol{font-weight:600;min-width:48px;text-align:right}',
  'canvas{width:100%;height:auto;display:block;border-radius:10px;touch-action:manipulation;background:#000;-webkit-touch-callout:none;-webkit-user-select:none;user-select:none}',
  '.btns{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}',
  '.btns button{flex:1;padding:10px;border-radius:10px;border:1px solid var(--line);background:var(--bg);color:var(--text);font:inherit;font-size:14px}',
  '#save{position:fixed;left:16px;right:16px;bottom:16px;max-width:448px;margin:0 auto;padding:14px;border:0;border-radius:14px;background:var(--accent);color:#fff;font:inherit;font-weight:600;font-size:17px}'
].join('\n');

var SCRIPT = function () {
  /* global SETTINGS, VIEW */
  var WALL_COLS = 8, WALL_ROWS = 4, FLOOR_COLS = 16, FLOOR_ROWS = 7;
  var WALL_Z = -1.25, PANEL = 0.9, TILE = 0.45, NEAR = 1.6;
  var X0 = -(WALL_COLS / 2) * PANEL - PANEL / 2;

  var room = SETTINGS.room.slice();
  var cam = VIEW.cam;
  var cp = Math.cos(cam.pitch), sp = Math.sin(cam.pitch);

  function project(x, y, z) {
    var dy = y - cam.ty, dz = z - cam.tz;
    var py = dy * cp - dz * sp;
    var zc = cam.dist - (dz * cp + dy * sp);
    var f = cam.scale * cam.dist / zc;
    return [cam.cx + (x - cam.tx) * f, cam.cy - py * f];
  }

  // A number per tile: bits 0-3 say which quarters are dark (x half + 2 *
  // row half, from the bottom-left of a wall panel / back-left of a floor
  // tile), TILE_SPLIT that it shows as four small tiles.
  var TILE_SPLIT = 0x10, TILE_DARK = 0x0F;

  // Every tile with its screen polygons, wall first. place(u0, v0, u1, v1)
  // gives the polygon of a part of the tile, in fractions of its size.
  var tiles = [];
  function addTile(i, floor, x0, b0, size) {
    function place(u0, v0, u1, v1) {
      var xa = x0 + u0 * size, xb = x0 + u1 * size;
      var ba = b0 + v0 * size, bb = b0 + v1 * size;
      if (floor) {
        ba = Math.min(ba, NEAR);
        bb = Math.min(bb, NEAR);
        return [project(xa, 0, ba), project(xb, 0, ba), project(xb, 0, bb), project(xa, 0, bb)];
      }
      return [project(xa, ba, WALL_Z), project(xb, ba, WALL_Z), project(xb, bb, WALL_Z), project(xa, bb, WALL_Z)];
    }
    var quarters = [];
    for (var q = 0; q < 4; q++) {
      var u = (q & 1) / 2, v = (q >> 1) / 2;
      quarters.push(place(u, v, u + 0.5, v + 0.5));
    }
    tiles.push({ i: i, floor: floor, pts: place(0, 0, 1, 1), quarters: quarters,
                 middle: place(0.25, 0.25, 0.75, 0.75) });
  }
  var r, c;
  for (r = 0; r < WALL_ROWS; r++) {
    for (c = 0; c < WALL_COLS; c++) addTile(r * WALL_COLS + c, false, X0 + c * PANEL, r * PANEL, PANEL);
  }
  for (r = 0; r < FLOOR_ROWS; r++) {
    for (c = 0; c < FLOOR_COLS; c++) {
      addTile(WALL_COLS * WALL_ROWS + r * FLOOR_COLS + c, true, X0 + c * TILE, WALL_Z + r * TILE, TILE);
    }
  }

  var canvas = document.getElementById('room');
  var ctx = canvas.getContext('2d');
  var dpr = Math.max(1, Math.min(3, window.devicePixelRatio || 1));
  canvas.width = VIEW.w * dpr;
  canvas.height = VIEW.h * dpr;

  var turret = new Image();
  turret.onload = draw;
  turret.src = VIEW.png;

  // taps on the turret itself don't change the tile behind it
  var turretAlpha = null;
  function onTurret(x, y) {
    if (!turretAlpha) {
      if (!turret.complete || !turret.naturalWidth) return false;
      try {
        var off = document.createElement('canvas');
        off.width = VIEW.w;
        off.height = VIEW.h;
        var o = off.getContext('2d');
        o.drawImage(turret, 0, 0, VIEW.w, VIEW.h);
        turretAlpha = o.getImageData(0, 0, VIEW.w, VIEW.h).data;
      } catch (e) {
        return false;
      }
    }
    // anything solid within a few pixels counts (the mesh has hairline gaps)
    var px = Math.floor(x), py = Math.floor(y);
    for (var dy = -3; dy <= 3; dy++) {
      for (var dx = -3; dx <= 3; dx++) {
        var qx = px + dx, qy = py + dy;
        if (qx >= 0 && qy >= 0 && qx < VIEW.w && qy < VIEW.h
            && turretAlpha[(qy * VIEW.w + qx) * 4 + 3] > 128) {
          return true;
        }
      }
    }
    return false;
  }

  var COLORS = {
    wall: ['#e6e6e6', '#161616'], floor: ['#f3f3f3', '#202020'],
    wallSeam: ['#8a8a8a', '#000'], floorSeam: ['#b4b4b4', '#000']
  };

  // The two grids at quarter-tile resolution, as on the watch
  var GRIDS = [
    { floor: false, cols: WALL_COLS, rows: WALL_ROWS, base: 0, cell: PANEL, b0: 0 },
    { floor: true, cols: FLOOR_COLS, rows: FLOOR_ROWS, base: WALL_COLS * WALL_ROWS, cell: TILE, b0: WALL_Z }
  ];
  function qTile(g, sc, sr) { return room[g.base + (sr >> 1) * g.cols + (sc >> 1)]; }
  function qDark(g, sc, sr) { return (qTile(g, sc, sr) >> ((sc & 1) + 2 * (sr & 1))) & 1; }
  function qPoint(g, sc, sr) {
    var x = X0 + sc * g.cell / 2, b = g.b0 + sr * g.cell / 2;
    return g.floor ? project(x, 0, Math.min(b, NEAR)) : project(x, b, WALL_Z);
  }

  function seam(p, q, color) {
    ctx.beginPath();
    ctx.moveTo(p[0], p[1]);
    ctx.lineTo(q[0], q[1]);
    ctx.strokeStyle = color;
    ctx.stroke();
  }

  // grey between two light tiles, black between two dark ones, none where
  // light meets dark
  function drawSeams() {
    ctx.lineWidth = 1.2;
    ctx.lineCap = 'butt';
    GRIDS.forEach(function (g) {
      var nc = g.cols * 2, nr = g.rows * 2, colors = g.floor ? COLORS.floorSeam : COLORS.wallSeam;
      var c, r, d;
      for (c = 1; c < nc; c++) {
        for (r = 0; r < nr; r++) {
          if ((c & 1) && !(qTile(g, c, r) & TILE_SPLIT)) continue;
          d = qDark(g, c - 1, r);
          if (d === qDark(g, c, r)) seam(qPoint(g, c, r), qPoint(g, c, r + 1), colors[d]);
        }
      }
      for (r = 1; r < nr; r++) {
        for (c = 0; c < nc; c++) {
          if ((r & 1) && !(qTile(g, c, r) & TILE_SPLIT)) continue;
          d = qDark(g, c, r - 1);
          if (d === qDark(g, c, r)) seam(qPoint(g, c, r), qPoint(g, c + 1, r), colors[d]);
        }
      }
    });
    // where the wall meets the floor (a wall quarter is two floor quarters wide)
    var wall = GRIDS[0], floor = GRIDS[1];
    for (var fc = 0; fc < FLOOR_COLS * 2; fc++) {
      var dw = qDark(wall, fc >> 1, 0);
      if (dw === qDark(floor, fc, 0)) seam(qPoint(floor, fc, 0), qPoint(floor, fc + 1, 0), COLORS.wallSeam[dw]);
    }
  }

  function path(pts) {
    ctx.beginPath();
    ctx.moveTo(pts[0][0], pts[0][1]);
    for (var k = 1; k < pts.length; k++) ctx.lineTo(pts[k][0], pts[k][1]);
    ctx.closePath();
  }

  function fillPoly(t, pts, dark) {
    // fill only: an outline in the tile's own colour would spill over onto
    // the next tile and show as a grey line along a black tile's edge
    path(pts);
    ctx.fillStyle = (t.floor ? COLORS.floor : COLORS.wall)[dark];
    ctx.fill();
  }

  function draw() {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = '#000';
    ctx.fillRect(0, 0, VIEW.w, VIEW.h);
    ctx.lineJoin = 'round';
    tiles.forEach(function (t) {
      var v = room[t.i];
      if (v & TILE_SPLIT) {
        for (var q = 0; q < 4; q++) fillPoly(t, t.quarters[q], (v >> q) & 1);
      } else {
        fillPoly(t, t.pts, v & 1);
      }
    });
    drawSeams();
    if (turret.complete && turret.naturalWidth) ctx.drawImage(turret, 0, 0, VIEW.w, VIEW.h);
  }

  function inside(pts, x, y) {
    var hit = false;
    for (var a = 0, b = pts.length - 1; a < pts.length; b = a++) {
      if ((pts[a][1] > y) !== (pts[b][1] > y)
          && x < (pts[b][0] - pts[a][0]) * (y - pts[a][1]) / (pts[b][1] - pts[a][1]) + pts[a][0]) {
        hit = !hit;
      }
    }
    return hit;
  }

  // the tile under a canvas point, or null (floor tiles are drawn last, so
  // they are checked first; the turret itself blocks)
  function tileAt(x, y) {
    if (onTurret(x, y)) return null;
    for (var k = tiles.length - 1; k >= 0; k--) {
      if (inside(tiles[k].pts, x, y)) return tiles[k];
    }
    return null;
  }

  function quarterAt(t, x, y) {
    for (var q = 0; q < 4; q++) {
      if (inside(t.quarters[q], x, y)) return q;
    }
    return 0;
  }

  // tap: switch the tile (or the small tile) between white and black
  function tap(x, y) {
    var t = tileAt(x, y);
    if (!t) return;
    var v = room[t.i];
    if (v & TILE_SPLIT) {
      room[t.i] = v ^ (1 << quarterAt(t, x, y));
    } else {
      room[t.i] = (v & 1) ? 0 : TILE_DARK;
    }
    draw();
  }

  // hold: a big tile splits into four small ones; holding where the four
  // small ones meet joins them back, in the colour of the one held
  function hold(x, y) {
    var t = tileAt(x, y);
    if (!t) return;
    var v = room[t.i];
    if (!(v & TILE_SPLIT)) {
      room[t.i] = v | TILE_SPLIT;
    } else if (inside(t.middle, x, y)) {
      room[t.i] = (v >> quarterAt(t, x, y)) & 1 ? TILE_DARK : 0;
    } else {
      return;
    }
    if (navigator.vibrate) navigator.vibrate(25);
    draw();
  }

  var HOLD_MS = 450, MOVE_PX = 10;
  var press = null;
  function canvasPoint(e) {
    var rect = canvas.getBoundingClientRect();
    return [(e.clientX - rect.left) * VIEW.w / rect.width, (e.clientY - rect.top) * VIEW.h / rect.height];
  }
  canvas.addEventListener('pointerdown', function (e) {
    var p = canvasPoint(e);
    press = { x: e.clientX, y: e.clientY, p: p, held: false };
    press.timer = setTimeout(function () {
      if (!press) return;
      press.held = true;
      hold(p[0], p[1]);
    }, HOLD_MS);
  });
  canvas.addEventListener('pointermove', function (e) {
    if (press && Math.abs(e.clientX - press.x) + Math.abs(e.clientY - press.y) > MOVE_PX) {
      clearTimeout(press.timer);  // it's a scroll, not a press
      press = null;
    }
  });
  canvas.addEventListener('pointerup', function () {
    if (!press) return;
    clearTimeout(press.timer);
    if (!press.held) tap(press.p[0], press.p[1]);
    press = null;
  });
  canvas.addEventListener('pointercancel', function () {
    if (press) clearTimeout(press.timer);
    press = null;
  });
  canvas.addEventListener('contextmenu', function (e) { e.preventDefault(); });

  function setAll(v) {
    for (var k = 0; k < room.length; k++) room[k] = v;
    draw();
  }
  document.getElementById('white').onclick = function () { setAll(0); };
  document.getElementById('black').onclick = function () { setAll(TILE_DARK); };
  document.getElementById('reset').onclick = function () {
    room = SETTINGS.defaultRoom.slice();
    draw();
  };

  var showTime = document.getElementById('showTime');
  var volume = document.getElementById('volume');
  var volLabel = document.getElementById('vol');
  showTime.checked = SETTINGS.showTime;
  volume.value = SETTINGS.volume;
  function volText() {
    volLabel.textContent = +volume.value === 0 ? 'Off' : volume.value + '%';
  }
  volume.oninput = volText;
  volText();

  document.getElementById('save').onclick = function () {
    var result = { showTime: showTime.checked, volume: +volume.value, room: room };
    location.href = 'pebblejs://close#' + encodeURIComponent(JSON.stringify(result));
  };

  draw();
};

// JSON that is safe inside a <script> tag
function scriptJson(value) {
  return JSON.stringify(value).replace(/</g, '\\u003c');
}

module.exports = function (settings, view) {
  return '<!doctype html><html lang="en"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width,initial-scale=1">' +
    '<title>Portal Turret</title><style>' + CSS + '</style></head><body>' +
    '<h1>Portal Turret</h1><p class="sub">Settings for the watchface</p>' +

    '<h2>Clock</h2><div class="card"><label class="row" for="showTime">' +
    '<span>Show the time under the eye</span><input type="checkbox" id="showTime"></label></div>' +

    '<h2>Sounds</h2><div class="card"><div class="row"><span>Volume</span><span id="vol"></span></div>' +
    '<input type="range" id="volume" min="0" max="100" step="10">' +
    '<p class="hint">Voice lines and panel sounds, on Pebble Time 2 only. 0% turns them off.</p></div>' +

    '<h2>Test chamber</h2><div class="card">' +
    '<canvas id="room"></canvas>' +
    '<p class="hint">Tap a wall panel or floor tile to switch it between white and black. ' +
    'Hold a tile to split it into 4 small ones; hold the middle, where 4 small ones meet, to join them back.</p>' +
    '<div class="btns"><button id="white">All white</button><button id="black">All black</button>' +
    '<button id="reset">Default</button></div></div>' +

    '<button id="save">Save</button>' +
    '<script>var SETTINGS=' + scriptJson(settings) + ';var VIEW=' + scriptJson(view) + ';(' +
    SCRIPT.toString() + ')();</script></body></html>';
};
