/* The Anchor app (static/app.html) - PLAN v2.2, Skill Foundry/planning/anchor-app-shell-2026-09-29.
 *
 * His rules (2026-10-01): the Cave of Wonders is always the first tile and never closes; anything else opens
 * on click as a tile in focus; ONE thing in focus; tiles click back, close with x, drag to reorder; a
 * deliverable opens beside the cockpit that opened it.
 *
 * Frames: the Cave's frame lives for the whole session (it is always open and slow to load). The tile in
 * focus has the only other live frame; the frame of a tile that loses focus is dropped once the new one has
 * loaded (never inside the caller's own window.open call), and comes back from its last address on a click.
 * The tile list lives in memory: each start is the Cave alone.
 */
(function () {
  "use strict";
  var CAVE_URL = "/";
  var CAVE_ICON = "/vendor/brand/aladdin-high-seat-cave.png";
  var FRAME_SCRIPT = "/static/app-frame.js";
  var DROP_AFTER_MS = 15000;      // drop the old focus frame by then even if the new one never loads

  var strip = document.getElementById("strip");
  var stage = document.getElementById("stage");
  var tiles = [];                 // {id, kind: "cave"|"page", url, title, name, opener, frame, side}
  var focusId = "cave";
  var seq = 0;
  var pendingDrop = [];           // ids of tiles whose frame goes once the focus frame has loaded
  var dropTimer = null;

  // ---------- frames ----------
  function newFrame(src) {
    var f = document.createElement("iframe");
    f.className = "pane";
    f.setAttribute("allow", "clipboard-read; clipboard-write; fullscreen");
    stage.appendChild(f);
    f.addEventListener("load", function () { onLoad(f); });
    if (src) f.src = src;
    return f;
  }

  function arm(win) {             // pages that were not served with the script get it on every load
    try {
      if (!win || win.__anchorFrame || !win.document || !win.document.head) return;
      var s = win.document.createElement("script");
      s.src = FRAME_SCRIPT;
      win.document.head.appendChild(s);
    } catch (e) { /* not ours to arm */ }
  }

  function addressOf(win) {
    try { var h = win.location.href; return h === "about:blank" ? "" : h; } catch (e) { return ""; }
  }

  function titleOf(win, fallback) {
    try {
      var t = (win.document.title || "").trim();
      if (t) return t;
      var p = win.location.pathname;
      return p && p !== "blank" ? decodeURIComponent(p.split("/").filter(Boolean).pop() || fallback) : fallback;
    } catch (e) { return fallback; }
  }

  function onLoad(f) {
    var hit = findFrame(f);
    if (!hit) return;
    var win = f.contentWindow, t = hit.tile;
    arm(win);
    var url = addressOf(win);
    if (hit.side) {
      if (url) t.side.url = url;
      t.side.title = titleOf(win, "Deliverable");
      t.side.label.textContent = t.side.title;
      if (url && isPage(new URL(url).pathname)) promoteSide(t);   // a blank pane that became a page gets its own tile
    } else {
      if (url) t.url = url;
      if (t.kind !== "cave") t.title = titleOf(win, t.title || "Page");
      if (t.id === focusId) settle();
    }
    render();
  }

  function findFrame(f) {
    for (var i = 0; i < tiles.length; i++) {
      if (tiles[i].frame === f) return { tile: tiles[i], side: false };
      if (tiles[i].side && tiles[i].side.frame === f) return { tile: tiles[i], side: true };
    }
    return null;
  }

  // the tile a window belongs to (the window itself, or a frame nested inside a tile's page)
  function tileOfWindow(win) {
    for (var w = win, guard = 0; w && guard < 8; guard++) {
      for (var i = 0; i < tiles.length; i++) {
        var t = tiles[i];
        if (t.frame && t.frame.contentWindow === w) return { tile: t, side: false };
        if (t.side && t.side.frame.contentWindow === w) return { tile: t, side: true };
      }
      if (w === window || w.parent === w) break;
      w = w.parent;
    }
    return null;
  }

  // ---------- what an address is ----------
  function resolve(u, fromWin) {
    if (u === undefined || u === null || u === "" || String(u) === "about:blank") return { blank: true };
    var x;
    try { x = new URL(String(u), fromWin && fromWin.location ? fromWin.location.href : location.href); }
    catch (e) { return null; }
    if (x.origin !== location.origin || !/^https?:$/.test(x.protocol)) return null;
    return { url: x.href, path: x.pathname, q: x.searchParams };
  }

  function isDownload(r) {
    if (r.q.get("download") === "1") return true;
    if (r.path === "/api/steward/deliverable-file" && r.q.get("view") !== "1" &&
        /\.(docx|pptx|xlsx|zip|7z|exe|msi)$/i.test(r.q.get("path") || "")) return true;
    return false;
  }

  // Anchor's own pages get a tile of their own; everything else (a report, an artifact, a deliverable
  // file, a notebook) is something to read beside the page that opened it.
  function isPage(path) {
    return path === "/" || path === "/dashboard" || path === "/high-seat" || path === "/doctor" ||
           /^\/foundry\/?$/.test(path) || /^\/project\//.test(path) || /^\/steward\/v[13]\b/.test(path) ||
           /^\/static\/app\.html$/.test(path);
  }

  // ---------- the API the frames call (static/app-frame.js) ----------
  var api = {
    open: function (u, target, fromWin) {
      var r = resolve(u, fromWin);
      if (!r || (!r.blank && isDownload(r))) return null;       // the native call (the host hands it to Windows)
      if (!r.blank && r.path === "/static/app.html") return null;
      var name = target && !/^_(blank|self|parent|top)$/i.test(String(target)) ? String(target) : "";
      if (name) {                                               // a named window is reused
        for (var i = 0; i < tiles.length; i++) {
          var t = tiles[i];
          if (t.side && t.side.name === name) { if (!r.blank) t.side.frame.src = r.url; focus(t.id); return t.side.frame.contentWindow; }
          if (t.name === name && t.kind !== "cave") {
            if (!t.frame) t.frame = newFrame("");
            if (!r.blank) t.frame.src = r.url;
            focus(t.id); return t.frame.contentWindow;
          }
        }
      }
      var caller = tileOfWindow(fromWin);
      if (caller && caller.tile.kind !== "cave" && !caller.side && (r.blank || !isPage(r.path))) {
        return openSide(caller.tile, r, name);                  // beside the page that asked
      }
      var tile = { id: "t" + (++seq), kind: "page", url: r.blank ? "" : r.url, title: r.blank ? "Opening…" : labelFor(r),
                   name: name, opener: fromWin || null, frame: null, side: null };
      tiles.push(tile);
      tile.frame = newFrame(r.blank ? "" : r.url);
      if (r.blank) guardBlank(tile.frame, function () { closeTile(tile.id); });
      focus(tile.id);
      return tile.frame.contentWindow;
    },
    openerOf: function (win) {
      var hit = tileOfWindow(win);
      return hit && !hit.side && hit.tile.opener && hit.tile.opener !== win ? hit.tile.opener : null;
    },
    closeWindow: function (win) {
      var hit = tileOfWindow(win);
      if (!hit) return;
      if (hit.side) closeSide(hit.tile); else closeTile(hit.tile.id);
    }
  };
  window.ANCHOR_APP = api;

  // a caller's w.close() on a window that is still blank (a failed create) closes its tile; the property
  // lives on the blank window until its first navigation, which brings app-frame.js's own close()
  function guardBlank(f, close) {
    try { f.contentWindow.close = close; } catch (e) { /* not reachable */ }
  }

  function labelFor(r) {
    var p = r.q.get("path");
    if (p) return p.split(/[\\/]/).pop();
    return decodeURIComponent(r.path.split("/").filter(Boolean).pop() || "Page");
  }

  // ---------- the pane beside the dialogue ----------
  function openSide(tile, r, name) {
    if (!tile.side) {
      var box = document.createElement("section");
      box.className = "side";
      var bar = document.createElement("div"); bar.className = "bar";
      var label = document.createElement("span"); label.className = "name";
      var x = document.createElement("button"); x.className = "x"; x.type = "button"; x.title = "Close"; x.textContent = "×";
      x.addEventListener("click", function () { closeSide(tile); });
      bar.appendChild(label); bar.appendChild(x); box.appendChild(bar);
      var f = document.createElement("iframe");
      f.setAttribute("allow", "clipboard-read; clipboard-write; fullscreen");
      box.appendChild(f);
      stage.appendChild(box);
      f.addEventListener("load", function () { onLoad(f); });
      tile.side = { box: box, frame: f, label: label, url: "", title: "", name: name };
    }
    tile.side.name = name || tile.side.name;
    tile.side.title = r.blank ? "Opening…" : labelFor(r);
    tile.side.label.textContent = tile.side.title;
    if (r.blank) {
      // a second open replaces the pane: a fresh frame so the caller gets a clean blank window
      var old = tile.side.frame, nf = document.createElement("iframe");
      nf.setAttribute("allow", old.getAttribute("allow"));
      old.replaceWith(nf);
      nf.addEventListener("load", function () { onLoad(nf); });
      tile.side.frame = nf;
      guardBlank(nf, function () { closeSide(tile); });
    } else {
      tile.side.url = r.url;
      tile.side.frame.src = r.url;
    }
    if (tile.id !== focusId) focus(tile.id); else layout();
    return tile.side.frame.contentWindow;
  }

  function closeSide(tile) {
    if (!tile.side) return;
    tile.side.box.remove();
    tile.side = null;
    layout();
    render();
  }

  function promoteSide(tile) {
    var url = tile.side.url;
    closeSide(tile);
    api.open(url, "", window);
  }

  // ---------- focus ----------
  function focus(id) {
    var next = byId(id);
    if (!next) return;
    var prev = byId(focusId);
    if (prev && prev !== next) {
      try { var ae = prev.frame && prev.frame.contentDocument && prev.frame.contentDocument.activeElement; if (ae && ae.blur) ae.blur(); }
      catch (e) { /* the draft keeps itself */ }
      if (prev.kind !== "cave" && pendingDrop.indexOf(prev.id) < 0) pendingDrop.push(prev.id);
    }
    focusId = id;
    var k = pendingDrop.indexOf(id);
    if (k >= 0) pendingDrop.splice(k, 1);
    if (!next.frame) next.frame = newFrame(next.url || CAVE_URL);   // a dropped tile comes back from its address
    layout();
    render();
    if (frameReady(next.frame)) settle();
    clearTimeout(dropTimer);
    dropTimer = setTimeout(settle, DROP_AFTER_MS);
  }

  function frameReady(f) {
    try { return f.contentDocument && f.contentDocument.readyState === "complete" && addressOf(f.contentWindow) !== ""; }
    catch (e) { return false; }
  }

  // the new focus has loaded: the frames of tiles that lost focus go (their address stays on the tile)
  function settle() {
    var keep = [];
    pendingDrop.forEach(function (id) {
      var t = byId(id);
      if (!t || t.id === focusId) return;
      if (t.side) { t.side.box.remove(); t.side = null; }
      if (t.frame) { t.url = addressOf(t.frame.contentWindow) || t.url; t.frame.remove(); t.frame = null; }
    });
    pendingDrop = keep;
    layout();
  }

  function layout() {
    var f = byId(focusId);
    tiles.forEach(function (t) {
      if (t.frame) t.frame.hidden = t.id !== focusId;
      if (t.side) t.side.box.hidden = t.id !== focusId;
    });
    stage.classList.toggle("split", !!(f && f.side));
  }

  function closeTile(id) {
    var t = byId(id);
    if (!t || t.kind === "cave") return;                        // the Cave never closes
    var i = tiles.indexOf(t);
    if (t.side) t.side.box.remove();
    if (t.frame) t.frame.remove();
    tiles.splice(i, 1);
    var k = pendingDrop.indexOf(id);
    if (k >= 0) pendingDrop.splice(k, 1);
    if (focusId === id) focus((tiles[i - 1] || tiles[0]).id); else render();
  }

  function byId(id) { for (var i = 0; i < tiles.length; i++) if (tiles[i].id === id) return tiles[i]; return null; }

  // ---------- the strip ----------
  function render() {
    strip.textContent = "";
    tiles.forEach(function (t) {
      var el = document.createElement("div");
      el.className = "tile" + (t.kind === "cave" ? " cave" : "") + (t.id === focusId ? " focus" : "");
      el.tabIndex = 0;
      el.setAttribute("role", "button");
      el.dataset.id = t.id;
      if (t.kind === "cave") {
        var img = document.createElement("img"); img.src = CAVE_ICON; img.alt = "";
        el.appendChild(img);
      }
      var name = document.createElement("span"); name.className = "name";
      name.textContent = t.kind === "cave" ? "Cave of Wonders" : (t.title || "Page");
      el.title = name.textContent;
      el.appendChild(name);
      if (t.kind !== "cave") {
        var x = document.createElement("button"); x.className = "x"; x.type = "button"; x.title = "Close"; x.textContent = "×";
        x.addEventListener("click", function (ev) { ev.stopPropagation(); closeTile(t.id); });
        el.appendChild(x);
      }
      el.addEventListener("click", function () { if (!dragMoved) focus(t.id); });
      el.addEventListener("keydown", function (ev) { if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); focus(t.id); } });
      if (t.kind !== "cave") el.addEventListener("pointerdown", startDrag);
      strip.appendChild(el);
    });
  }

  // drag to reorder (pointer events, so a finger works too); the Cave stays first
  var dragMoved = false;
  function startDrag(ev) {
    if (ev.button !== 0 || (ev.target && ev.target.classList && ev.target.classList.contains("x"))) return;
    var el = ev.currentTarget, id = el.dataset.id, x0 = ev.clientX;
    dragMoved = false;
    function move(e) {
      if (!dragMoved && Math.abs(e.clientX - x0) < 6) return;
      dragMoved = true;
      el.classList.add("dragging");
      var over = document.elementFromPoint(e.clientX, e.clientY);
      var tEl = over && over.closest ? over.closest(".tile") : null;
      if (!tEl || tEl === el || tEl.classList.contains("cave")) return;
      var a = tiles.indexOf(byId(id)), b = tiles.indexOf(byId(tEl.dataset.id));
      if (a < 1 || b < 1) return;
      tiles.splice(b, 0, tiles.splice(a, 1)[0]);
      render();
      el = strip.querySelector('[data-id="' + id + '"]');
      if (el) el.classList.add("dragging");
    }
    function up() {
      document.removeEventListener("pointermove", move);
      document.removeEventListener("pointerup", up);
      if (el) el.classList.remove("dragging");
      setTimeout(function () { dragMoved = false; }, 0);
    }
    document.addEventListener("pointermove", move);
    document.addEventListener("pointerup", up);
  }

  // the focus tile's name follows its page's title
  setInterval(function () {
    var t = byId(focusId);
    if (!t || t.kind === "cave" || !t.frame) return;
    var now = titleOf(t.frame.contentWindow, t.title);
    if (now && now !== t.title) { t.title = now; render(); }
  }, 2000);

  // ---------- start: the Cave alone ----------
  var cave = { id: "cave", kind: "cave", url: CAVE_URL, title: "Cave of Wonders", name: "", opener: null, frame: null, side: null };
  tiles.push(cave);
  cave.frame = newFrame(CAVE_URL);
  layout();
  render();
})();
