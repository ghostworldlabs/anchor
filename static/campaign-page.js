/* The Campaign page (W3c, 2026-09-26; trimmed by its Rabbit read; the goal board W2 v2, 2026-09-29): the view toggle, the goal tiles that drag and open into their place, the lanes that open,
   the area filter, and every act on the record through /api/high-seat/campaign — each act a receipt with undo,
   one act in flight at a time; the seed's two questions and the park's trigger are asked on the card, never in a
   browser prompt; the composer talks to the steward through the effort's own say route. Nothing here invents
   data: the page was rendered from the record. */
(function () {
  'use strict';
  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function token() { try { return localStorage.getItem('anchor_token') || ''; } catch (e) { return ''; } }
  function headers() {
    var h = { 'Content-Type': 'application/json' };
    var t = token(); if (t) h['X-Anchor-Token'] = t;
    var b = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.build_id) || ''; if (b) h['X-Anchor-Build'] = b;
    return h;
  }
  function tokenQ() { var t = token(); return t ? ('?token=' + encodeURIComponent(t)) : ''; }
  var PID = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.campaign_pid) || '';
  function openWin(url) {
    var w = null; try { w = window.open('about:blank', '_blank'); } catch (e) { w = null; }
    if (!w || w === window) { receipt('The browser blocked the new window — allow popups and try again.', true); return; }
    try { w.opener = null; w.location.replace(url); w.focus(); } catch (e) { try { w.close(); } catch (_) {} }
  }
  var lastUndo = null;
  function receipt(text, bad, undo) {
    var r = $('#receipt'), t = $('#receiptText'), u = $('#undoBtn'); if (!r || !t) return;
    t.textContent = text; r.hidden = false; r.classList.toggle('bad', !!bad);
    lastUndo = undo || null; if (u) u.hidden = !undo;
  }
  // a receipt survives the reload that shows the changed board
  try { var kept = sessionStorage.getItem('campaign_receipt'); if (kept) { var k = JSON.parse(kept); receipt(k.text, k.bad, k.undo); sessionStorage.removeItem('campaign_receipt'); } } catch (e) {}

  // one act in flight at a time: a second click while the first is on its way is ignored until the reload
  var busy = false;
  function act(body, onDone) {
    if (busy) return;
    busy = true;
    body.pid = PID;
    fetch('/api/high-seat/campaign', { method: 'POST', headers: headers(), body: JSON.stringify(body) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.ok) {
          busy = false;
          if (j && j.undo) {   // the act landed in part and the writer refused the rest: the receipt says so and its undo is his (Grok's read of W2b)
            try { sessionStorage.setItem('campaign_receipt', JSON.stringify({ text: j.receipt || 'Refused.', bad: true, undo: j.undo })); } catch (e) {}
            location.reload(); return;
          }
          receipt((j && j.receipt) || 'Nothing was done.', true); return;
        }
        try { sessionStorage.setItem('campaign_receipt', JSON.stringify({ text: j.receipt, bad: false, undo: j.undo || null })); } catch (e) {}
        if (onDone) { busy = false; onDone(j); } else location.reload();
      })
      .catch(function () { busy = false; receipt('That did not go through — nothing was done.', true); });
  }
  var undoBtn = $('#undoBtn');
  if (undoBtn) undoBtn.addEventListener('click', function () { if (lastUndo) act(lastUndo); });

  // the seeds tile: closed by default, its head toggles it (John, 2026-09-27)
  var seedband = $('#seedband'), seedToggle = $('#seedToggle'), seedTog = $('#seedTog');
  if (seedToggle) seedToggle.addEventListener('click', function () {
    var open = seedband.classList.toggle('open');
    seedToggle.setAttribute('aria-expanded', open ? 'true' : 'false'); if (seedTog) seedTog.textContent = open ? 'Hide' : 'Show';
  });

  // the view: grouped ↔ calendar, the same record
  var grouped = $('#viewGrouped'), cal = $('#viewCal'), viewBtn = $('#viewBtn'), title = $('#viewTitle');
  function setView(which) {
    var isCal = which === 'cal';
    if (grouped) grouped.style.display = isCal ? 'none' : '';
    if (cal) cal.style.display = isCal ? '' : 'none';
    if (viewBtn) viewBtn.innerHTML = isCal ? '&#9707; Grouped view' : '&#128197; Calendar view';
    if (title) title.textContent = isCal ? 'Tiers against the five-week ruler' : 'Initiatives by tier';
  }
  if (viewBtn) viewBtn.addEventListener('click', function () { setView(cal && cal.style.display === 'none' ? 'cal' : 'grouped'); });

  // W2 v2 (2026-09-29, his lock): a goal opens into its place above the bands — one at a time; ?open= deep-links it
  var slot = $('#placeSlot'), openedId = null, boardEl = $('.board');
  function openPlace(id) {
    $$('.place').forEach(function (p) { p.hidden = true; });
    $$('.gtile.opened').forEach(function (t) { t.classList.remove('opened'); });
    openedId = null;
    if (boardEl) boardEl.classList.toggle('placed', !!id);
    if (!id) return;
    var p = $('#place-' + id); if (!p) return;
    if (slot) slot.appendChild(p);
    p.hidden = false; openedId = id;
    var t = $('.gtile[data-lane="' + id + '"]'); if (t) t.classList.add('opened');
    try { var u = new URL(location.href); u.searchParams.set('open', id); history.replaceState(null, '', u.toString()); } catch (e) {}
    if (boardEl) boardEl.scrollTop = 0;   // the list of goals stays in view on top, shortened to names; the place opens right under it
    var th = $('.gthread', p); if (th) th.scrollTop = th.scrollHeight;
  }
  $$('button[data-open]').forEach(function (b) { b.addEventListener('click', function () { var id = b.getAttribute('data-open'); openPlace(openedId === id ? null : id); }); });
  $$('[data-close]').forEach(function (b) { b.addEventListener('click', function () { openPlace(null); try { var u = new URL(location.href); u.searchParams.delete('open'); history.replaceState(null, '', u.toString()); } catch (e) {} }); });
  $$('.lane [data-act="toggle"]').forEach(function (b) { b.addEventListener('click', function () { var l = b.closest('.lane'); l.classList.toggle('open'); }); });
  $$('.pc[data-act="chip"]').forEach(function (c) { c.addEventListener('click', function () { setView('grouped'); openPlace(c.getAttribute('data-lane')); var row = $('.row[data-part="' + c.getAttribute('data-part') + '"]'); if (row) { row.scrollIntoView({ block: 'center' }); row.classList.add('hot'); setTimeout(function () { row.classList.remove('hot'); }, 1600); } }); });
  var closeAll = $('#closeAll'); if (closeAll) closeAll.addEventListener('click', function () { openPlace(null); $$('.lane.open').forEach(function (t) { t.classList.remove('open'); }); });
  $$('[data-goto]').forEach(function (g) { g.addEventListener('click', function () { setView('grouped'); openPlace(g.getAttribute('data-goto')); }); });
  if (boardEl && boardEl.getAttribute('data-place')) openPlace(boardEl.getAttribute('data-place'));

  // the area filter: dims, never removes, so the numbers stay true
  $$('.ac[data-area]').forEach(function (b) {
    b.addEventListener('click', function () {
      var a = b.getAttribute('data-area'), was = b.classList.contains('on');
      $$('.ac').forEach(function (x) { x.classList.remove('on'); });
      $$('.gtile, .lane').forEach(function (t) { t.classList.remove('dimmed'); });
      if (!was) { b.classList.add('on'); $$('.gtile, .lane').forEach(function (t) { var pl = t.classList.contains('gtile') ? $('#place-' + t.getAttribute('data-lane')) : t; if (((pl && pl.querySelector('.larea')) || {}).textContent.trim().toLowerCase() !== a) t.classList.add('dimmed'); }); }
    });
  });

  // ranks and tiers
  $$('[data-act="up"], [data-act="down"]').forEach(function (b) { b.addEventListener('click', function () { act({ act: 'rank', step: b.getAttribute('data-lane'), direction: b.getAttribute('data-act') }); }); });
  $$('.tsel[data-tiersel]').forEach(function (s) { s.addEventListener('change', function () { act({ act: 'move_tier', step: s.getAttribute('data-tiersel'), tier: s.value }); }); });

  // parts: rename, date, flag, park (its trigger picked on the row), tick
  $$('.rt[data-act="name"]').forEach(function (n) {
    n.addEventListener('click', function () {
      var v = window.prompt('Rename this part', n.textContent.trim()); if (v === null) return;
      act({ act: 'rename', step: n.getAttribute('data-part'), name: v });
    });
  });
  $$('[data-act="date"]').forEach(function (d) {
    d.addEventListener('click', function () {
      var v = window.prompt('Its date (YYYY-MM-DD), or blank to clear', ''); if (v === null) return;
      act({ act: 'date', step: d.getAttribute('data-part'), due: v.trim() || 'none' });
    });
  });
  function closeParkPicks() { $$('.parkpick').forEach(function (x) { x.parentNode.removeChild(x); }); }
  $$('[data-act="park"]').forEach(function (p) {
    p.addEventListener('click', function () {
      var row = p.closest('.row'), step = p.getAttribute('data-part'); if (!row) return;
      closeParkPicks();
      var box = document.createElement('div'); box.className = 'parkpick';
      box.innerHTML = '<span class="q">Park until when?</span>'
        + ['January', 'March', 'June'].map(function (w) { return '<button type="button" data-parkuntil="' + w + '">' + w + '</button>'; }).join('')
        + '<input type="text" data-parkfree placeholder="or say what it waits for" autocomplete="off">'
        + '<button type="button" data-parkgo="1">park</button><button type="button" data-parkcancel="1">cancel</button>';
      row.appendChild(box);
      $$('[data-parkuntil]', box).forEach(function (b) { b.addEventListener('click', function () { act({ act: 'park', step: step, waiting_on: b.getAttribute('data-parkuntil') }); }); });
      var free = $('[data-parkfree]', box);
      function go() { var v = (free.value || '').trim(); if (!v) { receipt('A park carries its trigger — say until when, or what.', true); free.focus(); return; } act({ act: 'park', step: step, waiting_on: v }); }
      $('[data-parkgo]', box).addEventListener('click', go);
      free.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); go(); } if (e.key === 'Escape') closeParkPicks(); });
      $('[data-parkcancel]', box).addEventListener('click', closeParkPicks);
      free.focus();
    });
  });
  $$('[data-act="unpark"]').forEach(function (p) { p.addEventListener('click', function () { act({ act: 'unpark', step: p.getAttribute('data-part') }); }); });
  $$('[data-act="flag"]').forEach(function (p) { p.addEventListener('click', function () { act({ act: 'flag', step: p.getAttribute('data-part') }); }); });
  $$('[data-act="unflag"]').forEach(function (p) { p.addEventListener('click', function () { act({ act: 'unflag', step: p.getAttribute('data-part') }); }); });
  $$('[data-act="tick"]').forEach(function (p) { p.addEventListener('click', function () { if (p.disabled) return; act({ act: 'tick', step: p.getAttribute('data-part') }); }); });

  // add a part
  $$('.addline').forEach(function (line) {
    var kind = $('[data-add="kind"]', line), text = $('[data-add="text"]', line), proj = $('[data-add="project"]', line), date = $('[data-add="date"]', line), btn = $('[data-act="add"]', line);
    function sync() { var isP = kind.value === 'project'; proj.style.display = isP ? '' : 'none'; text.placeholder = isP ? 'a name for the part (optional)' : 'Add a part'; }
    kind.addEventListener('change', sync); sync();
    function go() { act({ act: 'add', initiative: btn.getAttribute('data-lane'), kind: kind.value, text: text.value, due: date.value.trim() || null, project_id: proj.value || null }); }
    btn.addEventListener('click', go);
    text.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); go(); } });
  });

  // seeds → initiatives: the two questions on the card; nothing is created until Create it
  $$('.seed').forEach(function (card) {
    var mk = $('[data-act="promote"]', card), pick = $('.pick', card), go = $('[data-pickgo]', card); if (!mk || !pick || !go) return;
    function chosen(sel) { var b = $(sel + '.on', pick); return b ? b.getAttribute(sel.replace('[', '').replace(']', '')) : ''; }
    function label() { go.textContent = 'Create it in tier ' + (chosen('[data-picktier]') || '3'); }
    mk.addEventListener('click', function () { $$('.seed .pick').forEach(function (x) { if (x !== pick) x.hidden = true; }); pick.hidden = false; mk.hidden = true; label(); });
    $$('[data-picktier]', pick).forEach(function (b) { b.addEventListener('click', function () { $$('[data-picktier]', pick).forEach(function (x) { x.classList.remove('on'); }); b.classList.add('on'); label(); }); });
    $$('[data-pickarea]', pick).forEach(function (b) { b.addEventListener('click', function () { $$('[data-pickarea]', pick).forEach(function (x) { x.classList.remove('on'); }); b.classList.add('on'); }); });
    $('[data-pickcancel]', pick).addEventListener('click', function () { pick.hidden = true; mk.hidden = false; });
    go.addEventListener('click', function () { act({ act: 'promote', seed: go.getAttribute('data-pickgo'), tier: chosen('[data-picktier]') || '3', area: chosen('[data-pickarea]') || null }); });
  });

  // W2 (PLAN v1.3, 2026-09-30): a goal tile drags into another tier or into Seed goals (tier 3). Every drop is ONE
  // act — place — through the same route, with undo; there is no order inside a tier. Nothing moves on the page
  // until the record says so. Seats (Active, On deck) live at the High Seat.
  var dragId = null, dragFrom = null;
  function clearMarks() { $$('.band.over').forEach(function (l) { l.classList.remove('over'); }); }
  $$('.gtile[draggable="true"]').forEach(function (r) {
    r.addEventListener('dragstart', function (e) {
      dragId = r.getAttribute('data-lane'); dragFrom = r.getAttribute('data-band'); r.classList.add('dragging');
      try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', dragId); } catch (_) {}
    });
    r.addEventListener('dragend', function () { r.classList.remove('dragging'); clearMarks(); dragId = null; dragFrom = null; });
  });
  $$('.band[data-band="1"], .band[data-band="2"], .band[data-band="3"]').forEach(function (band) {
    band.addEventListener('dragover', function (e) {
      if (!dragId) return;
      e.preventDefault(); try { e.dataTransfer.dropEffect = 'move'; } catch (_) {}
      clearMarks(); band.classList.add('over');
    });
    band.addEventListener('dragleave', function (e) { if (!band.contains(e.relatedTarget)) clearMarks(); });
    band.addEventListener('drop', function (e) {
      if (!dragId) return;
      e.preventDefault();
      var to = band.getAttribute('data-band'), id = dragId, from = dragFrom; clearMarks();
      if (to === from) return;
      act({ act: 'place', step: id, band: to, position: 0 });      // the tier only
    });
  });
  // the boneyard: folded, never deleted
  var boneTog = $('#boneTog'), boneFold = $('#boneFold');
  if (boneTog && boneFold) boneTog.addEventListener('click', function () { boneFold.hidden = !boneFold.hidden; boneTog.setAttribute('aria-expanded', boneFold.hidden ? 'false' : 'true'); boneTog.textContent = (boneFold.hidden ? 'show' : 'hide') + boneTog.textContent.replace(/^(show|hide)/, ''); });

  // the goal's place: revise the goal, set the pace, take it up or bench it — each one act with undo
  $$('.place .g[data-goal-text]').forEach(function (g) {
    g.addEventListener('click', function () {
      if (g.querySelector('textarea')) return;
      var id = g.getAttribute('data-goal-text'), old = g.classList.contains('empty') ? '' : g.textContent.trim();
      if (/^not written yet/.test(old)) old = '';
      g.innerHTML = '<textarea></textarea><div class="row2"><span class="hint">one line with undo · written as the goal\u2019s done-when on the record</span><button type="button" class="save">Save</button><button type="button" class="mini">cancel</button></div>';
      var ta = g.querySelector('textarea'); ta.value = old; ta.focus();
      g.querySelector('.save').addEventListener('click', function (e) { e.stopPropagation(); var v = ta.value.trim(); if (!v) { receipt('A goal is a sentence — say what done looks like.', true); return; } act({ act: 'done_when', step: id, text: v }); });
      g.querySelector('.mini').addEventListener('click', function (e) { e.stopPropagation(); g.innerHTML = old ? old.replace(/</g, '&lt;') : '<span class="dim">not written yet — say what done looks like</span>'; });
      ta.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); g.querySelector('.save').click(); } if (e.key === 'Escape') g.querySelector('.mini').click(); });
    });
  });
  $$('.place [data-pace]').forEach(function (s) {
    s.addEventListener('click', function () {
      var id = s.getAttribute('data-pace'); var inp = document.createElement('input'); inp.type = 'date'; inp.title = 'the pace — the date you drive this goal toward; clear it to drop the pace';
      s.replaceWith(inp); inp.focus();
      inp.addEventListener('change', function () { act({ act: 'pace', step: id, when: inp.value || 'none' }); });
      inp.addEventListener('blur', function () { if (document.body.contains(inp)) inp.replaceWith(s); });
    });
  });

  // the seats (W2b-2, 2026-09-30): a cockpit or a desk item goes on deck or active, or back into its goal — one act with undo
  $$('.place [data-seat]').forEach(function (b) { b.addEventListener('click', function () { act({ act: 'seat', step: b.getAttribute('data-step'), seat: b.getAttribute('data-seat') }); }); });
  $$('.place [data-home]').forEach(function (b) { b.addEventListener('click', function () { act({ act: 'home', step: b.getAttribute('data-home') }); }); });

  // ── the dialogue (W2b-1, 2026-09-30; W2b-3 the same day, his word: "it should be interactive and able for me to follow
  // what is going on, ask, discuss") ──────────────────────────────────────────────────────────────────────────────
  // The page long-polls the cockpit's own event stream (/api/steward/events, the one the AI Cockpit uses) from the
  // moment it opens — the cockpit's own rule: opening the page resumes a parked steward that has work kept for it, and
  // a brand-new one is never woken by a mere view. What the steward writes lands as it writes: in the panel's dialogue,
  // and when the turn was sent from a goal's brainstorm, there too. One log, two views. A turn that changed the record
  // reloads the board with the receipt kept. The steward's state (parked · waking · listening · working) stands at
  // the dialogue's head, read from the same poll.
  var BOOT_STAMP = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.stamp) || '';
  var STEWARD = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.steward) || 'The steward';
  var live = { seq: 0, polling: false, target: null, goal: null, line: null, epoch: null, skipJohn: '' };
  function goalName(id) { var n = $('#place-' + id + ' .pname'); return (n && n.textContent.trim()) || id; }
  function exLi(who, text, cls, goal) {
    var li = document.createElement('li');
    li.className = 'exrow ' + (who === 'you' ? 'you' : (who === 'st' ? 'st' : 'sysl')) + (cls ? ' ' + cls : '');
    li.innerHTML = '<div class="exw ' + (who === 'you' ? 'you' : 'st') + '"><span class="w"></span><span class="t"></span></div><div class="ext"></div>';
    li.querySelector('.w').textContent = who === 'you' ? 'You' : (who === 'st' ? STEWARD : '');
    if (goal) { var c = document.createElement('button'); c.className = 'gchip'; c.title = 'open this goal'; c.textContent = 'about ' + goalName(goal); li.querySelector('.exw').insertBefore(c, li.querySelector('.t')); c.addEventListener('click', function () { openPlace(goal); }); }
    li.querySelector('.ext').textContent = text;
    return li;
  }
  function mainList() { return $('#exList'); }
  function settle(list) { list.scrollTop = list.scrollHeight; var sc = list.closest('.scroll'); if (sc) sc.scrollTop = sc.scrollHeight; }
  function put(list, li) { if (!list) return null; var fade = list.querySelector('.exfade'); if (fade) fade.remove(); list.appendChild(li); settle(list); return li; }
  // one log, two views: a line lands in the list that sent the turn and, when that is a goal's thread, in the
  // panel's dialogue as well, with the goal's chip
  function appendLine(who, text, cls) {
    var main = mainList(), tgt = live.target || main;
    var pair = { li: put(tgt, exLi(who, text, cls, tgt === main ? live.goal : null)), mi: null };
    if (tgt !== main) pair.mi = put(main, exLi(who, text, cls, live.goal));
    return pair;
  }
  function each(pair, f) { if (!pair) return; if (pair.li) f(pair.li); if (pair.mi) f(pair.mi); }
  function stateText(s) {
    if (!s) return '';
    if (s.busy) { var q = +(s.quiet_seconds || 0); return 'working' + (q > 300 ? ', quiet for ' + Math.floor(q / 60) + ' min' : '') + '…'; }
    if (!s.alive) return s.queued ? 'parked — ' + s.queued + ' of yours waits for it to wake' : 'parked — it wakes on your word';
    return s.queued ? 'listening · ' + s.queued + ' queued' : 'listening';
  }
  function showState(s) { var el = $('#exState'); if (!el || !s) return; el.textContent = stateText(s); el.setAttribute('data-state', s.busy ? 'busy' : (s.alive ? 'idle' : 'parked')); }
  // a turn that ended before this page saw its words (it was mid-turn when the page opened): the log has it
  function catchUp() {
    fetch('/api/steward/history?pid=' + encodeURIComponent(PID) + '&dir=', { headers: headers() })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var ts = (j && j.turns) || [], last = null;
        for (var i = ts.length - 1; i >= 0; i--) { var role = String(ts[i].role || '').toLowerCase(); if (ts[i].text && role !== 'john' && role !== 'you' && role !== 'user' && role !== 'human') { last = ts[i]; break; } }
        if (!last) return;
        var main = mainList(), rows = main ? $$('.exrow.st .ext', main) : [], txt = String(last.text).replace(/\s+/g, ' ').trim();
        if (rows.length && rows[rows.length - 1].textContent.replace(/\s+/g, ' ').trim() === txt) return;
        live.goal = last.goal || null; live.target = null; appendLine('st', txt, ''); live.goal = null;
      })
      .catch(function () {});
  }
  function handleEvent(ev) {
    if (!ev || ev.tick) return;
    if (ev.t === 'delta') { if (!live.line) live.line = appendLine('st', '', 'live'); each(live.line, function (li) { li.querySelector('.ext').textContent += (ev.text || ''); settle(li.parentNode); }); return; }
    if (ev.t === 'turn_end') { if (live.line) { each(live.line, function (li) { li.classList.remove('live'); }); live.line = null; } else catchUp(); live.target = null; live.goal = null; return; }
    if (ev.t === 'john') { var t = String(ev.text || ''); if (live.skipJohn && t === live.skipJohn) { live.skipJohn = ''; return; } live.target = null; live.goal = null; appendLine('you', t, ''); return; }
    if (ev.t === 'sys' && ev.text) { appendLine('sys', ev.text, 'dim'); return; }
    if (ev.t === 'tool') { if (!live.line) live.line = appendLine('st', '', 'live'); each(live.line, function (li) { var w = li.querySelector('.exw .t'); if (w) w.textContent = 'working…'; }); return; }
  }
  function primeSeq() {   // the ring's current top, so the poll never replays lines the log below already shows
    return fetch('/api/steward/events?pid=' + encodeURIComponent(PID) + '&dir=&since=0', { headers: headers() })
      .then(function (r) { return r.json(); })
      .then(function (j) { (j.events || []).forEach(function (ev) { live.seq = Math.max(live.seq, ev.seq || 0); }); if (j.state && j.state.epoch !== undefined) live.epoch = j.state.epoch; showState(j.state); })
      .catch(function () {});
  }
  function pollLoop() {
    if (live.polling) return; live.polling = true;
    (function step() {
      fetch('/api/steward/events?pid=' + encodeURIComponent(PID) + '&dir=&since=' + live.seq, { headers: headers() })
        .then(function (r) { return r.json(); })
        .then(function (j) {
          var ep = j.state && j.state.epoch;
          if (ep !== undefined && live.epoch !== null && ep !== live.epoch) { live.seq = 0; live.epoch = ep; appendLine('sys', '— the steward reconnected —', 'dim'); }
          else if (ep !== undefined) live.epoch = ep;
          showState(j.state);
          (j.events || []).forEach(function (ev) { live.seq = Math.max(live.seq, ev.seq || 0); handleEvent(ev); });
          if (j.stamp && BOOT_STAMP && j.stamp !== BOOT_STAMP && !live.line) {
            try { sessionStorage.setItem('campaign_receipt', JSON.stringify({ text: 'The steward changed the record — the board is reloaded.', bad: false, undo: null })); } catch (e) {}
            location.reload(); return;
          }
          setTimeout(step, 250);
        })
        .catch(function () { setTimeout(step, 3000); });
    })();
  }
  function sendToSteward(text, goal, list, btn, box, DK) {
    btn.disabled = true; btn.textContent = 'Thinking…';
    (live.polling ? Promise.resolve() : primeSeq()).then(function () {
      return fetch('/api/steward/say', { method: 'POST', headers: headers(), body: JSON.stringify({ pid: PID, dir: '', text: text, goal: goal || undefined }) });
    })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        btn.disabled = false; btn.textContent = 'Send';
        if (j && j.error === 'build-mismatch') {   // a stale tab: the draft is kept in this browser; the renewed page puts it back
          try { sessionStorage.setItem('campaign_receipt', JSON.stringify({ text: 'This page was older than the server — it is renewed; your unsent text is back in the box, send it again.', bad: true, undo: null })); } catch (e) {}
          location.reload(); return;
        }
        if (!j || j.ok === false) {
          var why = (j && (j.say || j.receipt || j.error || j.message)) || 'No answer came back — nothing was done.';
          if (j && j.undo) {   // a verb that landed in part: the refusal and its undo survive the reload onto the record as it stands
            try { sessionStorage.setItem('campaign_receipt', JSON.stringify({ text: why, bad: true, undo: j.undo })); } catch (e) {}
            location.reload(); return;
          }
          receipt(why, true); live.target = list; live.goal = goal || null; appendLine('sys', 'Not sent — ' + why, 'dim'); live.target = null; live.goal = null; return;
        }
        try { if (DK) localStorage.removeItem(DK); } catch (e) {}
        if (j.campaign_act && !j.read_only) {   // a Campaign verb: the record changed; the receipt and its undo survive the reload
          try { sessionStorage.setItem('campaign_receipt', JSON.stringify({ text: j.say, bad: false, undo: j.undo || null })); } catch (e) {}
          location.reload(); return;
        }
        box.value = '';
        live.target = list; live.goal = goal || null; live.line = null; live.skipJohn = text;
        appendLine('you', text);
        if (j.queued) appendLine('sys', 'queued — the steward is mid-turn; yours goes next', 'dim');
        receipt(goal ? 'Said to the steward about this goal — it answers as it writes.' : 'Said — the steward answers below as it writes.');
        pollLoop();
      })
      .catch(function () { btn.disabled = false; btn.textContent = 'Send'; receipt('That did not go through — nothing was done.', true); });
  }
  // live from the open: the ring's top first (so the log shown below is not replayed), then the stream
  if (PID && mainList()) primeSeq().then(pollLoop);
  $$('.place .gsay').forEach(function (box) {
    var goal = box.getAttribute('data-goal'), btn = $('.gsend[data-goal="' + goal + '"]'), list = $('.gthread[data-thread="' + goal + '"]');
    var DK = 'anchor:draft:goal:' + PID + ':' + goal, dt = null;
    try { var kept = localStorage.getItem(DK); if (kept && kept.trim() && !box.value.trim()) box.value = kept; } catch (e) {}
    box.addEventListener('input', function () { clearTimeout(dt); dt = setTimeout(function () { try { if (box.value.trim()) localStorage.setItem(DK, box.value); else localStorage.removeItem(DK); } catch (e) {} }, 250); });
    function go(text) { text = (text || box.value || '').trim(); if (!text || btn.disabled) return; sendToSteward(text, goal, list, btn, box, DK); }
    btn.addEventListener('click', function () { go(); });
    box.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); go(); } });
    $$('.chips [data-say]', box.closest('.gconv')).forEach(function (c) { c.addEventListener('click', function () { go(c.getAttribute('data-say')); }); });
  });

  // the tools
  $$('.tool[data-tool]').forEach(function (b) {
    b.addEventListener('click', function () {
      var k = b.getAttribute('data-tool');
      if (k === 'doctor') openWin('/doctor' + tokenQ());
      else if (k === 'zombie') openWin('/api/rnd/zombie_hunter_report' + tokenQ());
      else if (k === 'foundry') openWin('/foundry');
    });
  });

  // the composer: the effort's own say route
  var say = $('#say'), send = $('#sendBtn');
  // R12 (2026-09-28, John): the unsent text is kept in this browser on every keystroke and put back after a crash,
  // a restart or a reload; a delivered turn clears it
  var DRAFT_KEY = 'anchor:draft:campaign:' + PID, _draftT = null;
  function saveDraft() { try { if (say && say.value.trim()) localStorage.setItem(DRAFT_KEY, say.value); else localStorage.removeItem(DRAFT_KEY); } catch (e) {} }
  function clearDraft() { try { localStorage.removeItem(DRAFT_KEY); } catch (e) {} }
  if (say) {
    say.addEventListener('input', function () { clearTimeout(_draftT); _draftT = setTimeout(saveDraft, 250); });
    window.addEventListener('beforeunload', saveDraft);
    try { var keptDraft = localStorage.getItem(DRAFT_KEY); if (keptDraft && keptDraft.trim() && !say.value.trim()) { say.value = keptDraft; receipt('Your unsent text is back in the box.'); } } catch (e) {}
  }
  function doSend() {
    var text = (say.value || '').trim(); if (!text || send.disabled) return;
    sendToSteward(text, null, $('#exList'), send, say, DRAFT_KEY);
  }
  if (send) send.addEventListener('click', doSend);
  if (say) say.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doSend(); } });
  // a redeploy reloads the open page, as the High Seat does (the verification law: a mechanism, not "refresh"):
  // /api/version every 30 s; a build other than the one this page booted with reloads it once — never while he is
  // typing (W2b-3, 2026-09-30: his sends from a tab older than the server were refused as a build mismatch and
  // looked like nothing)
  (function () {
    var mine = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.build_id) || '';
    if (!mine) return;
    function typing() { var a = document.activeElement; return !!(a && (a.tagName === 'TEXTAREA' || a.tagName === 'INPUT') && (a.value || '').trim()); }
    setInterval(function () {
      fetch('/api/version', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
        var v = d && d.version; if (!v || v === mine || typing()) return;
        try { if (sessionStorage.getItem('campaign_reloaded_for') === String(v)) return; sessionStorage.setItem('campaign_reloaded_for', String(v)); } catch (e) {}
        location.reload();
      }).catch(function () {});
    }, 30000);
  })();
})();
