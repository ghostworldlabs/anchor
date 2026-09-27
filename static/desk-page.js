/* The Desk (W3b, 2026-09-26): John's tasks on the Campaign record, editable where they sit. Every change is one act
   on /api/high-seat/campaign — the same writer the Campaign page uses — answered by a receipt with Undo; one act in
   flight at a time; the list reloads to show the record as it now is. The filters, the calendar tabs and the
   inline editors are page-only. Nothing here invents data. */
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
  var TODAY = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.today) || new Date().toISOString().slice(0, 10);
  function openWin(url) {
    var w = null; try { w = window.open('about:blank', '_blank'); } catch (e) { w = null; }
    if (!w || w === window) { receipt('The browser blocked the new window — allow popups and try again.', true); return; }
    try { w.opener = null; w.location.replace(url); w.focus(); } catch (e) { try { w.close(); } catch (_) {} }
  }
  var lastUndo = null;
  function receipt(text, bad, undo) {
    var r = $('#receipt'), t = $('#receiptText'), u = $('#undoBtn'); if (!r || !t) return;
    t.textContent = text; r.classList.remove('none'); r.classList.toggle('bad', !!bad);
    var m = $('.r-mark', r); if (m) m.textContent = bad ? '!' : '✓';
    lastUndo = undo || null; if (u) u.hidden = !undo;
  }
  try { var kept = sessionStorage.getItem('desk_receipt'); if (kept) { var k = JSON.parse(kept); receipt(k.text, k.bad, k.undo); sessionStorage.removeItem('desk_receipt'); } } catch (e) {}

  var busy = false;
  function act(body) {
    if (busy) return;
    busy = true;
    body.pid = PID;
    fetch('/api/high-seat/campaign', { method: 'POST', headers: headers(), body: JSON.stringify(body) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.ok) { busy = false; receipt((j && j.receipt) || 'Nothing was done.', true); return; }
        try { sessionStorage.setItem('desk_receipt', JSON.stringify({ text: j.receipt, bad: false, undo: j.undo || null })); } catch (e) {}
        location.reload();
      })
      .catch(function () { busy = false; receipt('That did not go through — nothing was done.', true); });
  }
  var undoBtn = $('#undoBtn');
  if (undoBtn) undoBtn.addEventListener('click', function () { if (lastUndo) act(lastUndo); });

  // ── dates: 2026-10-03 · Oct 3 · 3 Oct · today · tomorrow · Tuesday · blank clears ──
  var MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'];
  var DAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
  function iso(d) { return d.getFullYear() + '-' + ('0' + (d.getMonth() + 1)).slice(-2) + '-' + ('0' + d.getDate()).slice(-2); }
  function daysIn(y, m) { return new Date(y, m + 1, 0).getDate(); }
  // a month-and-day stays in this year, as typed (a past day is a past day); Tuesday is the next Tuesday; today only
  // for the word; a day the calendar does not hold, in any shape, is refused by name and the old date kept
  function parseDate(s) {
    s = (s || '').trim().toLowerCase();
    if (!s) return 'none';
    var t = new Date(TODAY + 'T12:00:00'), y = t.getFullYear(), m, day, mon;
    m = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
    if (m) { var yy = parseInt(m[1], 10), mm = parseInt(m[2], 10) - 1, dd = parseInt(m[3], 10); if (mm < 0 || mm > 11 || dd < 1 || dd > daysIn(yy, mm)) return null; return iso(new Date(yy, mm, dd, 12)); }
    if (s === 'today') return iso(t);
    if (s === 'tomorrow') { t.setDate(t.getDate() + 1); return iso(t); }
    var di = DAYS.indexOf(s.slice(0, 3));
    if (di >= 0 && /^[a-z]+$/.test(s)) { var cur = (t.getDay() + 6) % 7; var ahead = (di - cur + 7) % 7 || 7; t.setDate(t.getDate() + ahead); return iso(t); }
    m = /^([a-z]+)\.?\s+(\d{1,2})$/.exec(s) || null;
    if (m) { mon = MONTHS.indexOf(m[1].slice(0, 3)); day = parseInt(m[2], 10); }
    else { m = /^(\d{1,2})\s+([a-z]+)\.?$/.exec(s); if (m) { mon = MONTHS.indexOf(m[2].slice(0, 3)); day = parseInt(m[1], 10); } }
    if (m && mon >= 0) { if (day < 1 || day > daysIn(y, mon)) return null; return iso(new Date(y, mon, day, 12)); }
    return null;
  }
  window.deskParseDate = parseDate;   // for the page's look; the page itself calls it above

  // ── filters: page-only; the counts say what is hidden ──
  var filter = 'all';
  var NOTES = { all: 'Every task, grouped by when it is wanted. Parked and Done fall to the bottom.',
    needs: 'Only the rows flagged ⚑ needs you.', dated: 'Only rows carrying a date, soonest first inside each group.',
    admin: 'Only rows tagged admin — the Desk’s own work.' };
  function passes(row) {
    if (filter === 'all') return true;
    if (filter === 'needs') return row.getAttribute('data-needs') === '1';
    if (filter === 'dated') return row.getAttribute('data-dated') === '1';
    if (filter === 'admin') return row.getAttribute('data-admin') === '1';
    return true;
  }
  function applyFilter() {
    $$('[data-filter]').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-filter') === filter); });
    var fn = $('#fnote'); if (fn) fn.textContent = NOTES[filter] || '';
    $$('.grp').forEach(function (g) {
      var rows = $$('.row', g), shown = 0;
      rows.forEach(function (r) { var ok = passes(r); r.hidden = !ok; if (ok) shown++; });
      var gc = $('.gc', g); if (gc) gc.textContent = rows.length && shown !== rows.length ? (shown + ' of ' + rows.length) : String(rows.length);
      var old = $('.gfilt', g); if (old) old.parentNode.removeChild(old);
      if (rows.length && !shown) { var p = document.createElement('p'); p.className = 'gempty gfilt'; p.textContent = 'Nothing here matches the filter — ' + rows.length + ' hidden.'; g.appendChild(p); }
    });
  }
  $$('[data-filter]').forEach(function (b) { b.addEventListener('click', function () { filter = b.getAttribute('data-filter'); applyFilter(); }); });

  // ── the rows: rename, date, retag, flag, park, remove ──
  function inlineEdit(el, value, placeholder, onSave) {
    var input = document.createElement('input'); input.className = 'inline'; input.value = value; input.placeholder = placeholder || '';
    var hint = document.createElement('div'); hint.className = 'ehint'; hint.textContent = 'Enter saves · Esc cancels';
    var parent = el.parentNode; el.hidden = true; parent.insertBefore(input, el); parent.insertBefore(hint, el); input.focus(); input.select();
    var done = false;
    function finish(save) {
      if (done) return; done = true;
      var v = input.value; parent.removeChild(input); parent.removeChild(hint); el.hidden = false;
      if (save && v.trim() !== value.trim()) onSave(v);
    }
    input.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); finish(true); } if (e.key === 'Escape') finish(false); });
    input.addEventListener('blur', function () { finish(true); });
  }
  $$('.rt[data-act="text"]').forEach(function (n) {
    n.addEventListener('click', function () {
      inlineEdit(n, n.textContent.trim(), 'the task, in words', function (v) { if (v.trim()) act({ act: 'rename', step: n.getAttribute('data-id'), name: v.trim() }); else receipt('A task needs its words — the old name is kept.', true); });
    });
  });
  $$('[data-act="date"]').forEach(function (d) {
    d.addEventListener('click', function () {
      var cur = d.classList.contains('dated') ? d.textContent.trim() : '';
      inlineEdit(d, cur, 'Oct 3 · Tuesday · today · 2026-10-03 · blank clears', function (v) {
        var when = parseDate(v);
        if (when === null) { receipt('I could not read “' + v.trim() + '” as a date — Oct 3, Tuesday, today or 2026-10-03; the old date is kept.', true); return; }
        act({ act: 'date', step: d.getAttribute('data-id'), due: when });
      });
    });
  });
  $$('.psel[data-retag]').forEach(function (s) { s.addEventListener('change', function () { act({ act: 'retag', step: s.getAttribute('data-retag'), initiative: s.value }); }); });
  $$('[data-act="flag"]').forEach(function (p) { p.addEventListener('click', function () { act({ act: 'flag', step: p.getAttribute('data-id') }); }); });
  $$('[data-act="unflag"]').forEach(function (p) { p.addEventListener('click', function () { act({ act: 'unflag', step: p.getAttribute('data-id') }); }); });
  $$('[data-act="unpark"]').forEach(function (p) { p.addEventListener('click', function () { act({ act: 'unpark', step: p.getAttribute('data-id') }); }); });
  $$('[data-act="tick"]').forEach(function (p) { p.addEventListener('click', function () { if (p.disabled) return; act({ act: 'tick', step: p.getAttribute('data-id') }); }); });
  $$('[data-act="del"]').forEach(function (p) { p.addEventListener('click', function () { act({ act: 'withdraw', step: p.getAttribute('data-id') }); }); });
  function closeParkPicks() { $$('.parkpick').forEach(function (x) { x.parentNode.removeChild(x); }); }
  $$('[data-act="park"]').forEach(function (p) {
    p.addEventListener('click', function () {
      var row = p.closest('.row'), step = p.getAttribute('data-id'); if (!row) return;
      closeParkPicks();
      var box = document.createElement('div'); box.className = 'parkpick';
      box.innerHTML = '<span class="q">Park until when?</span>'
        + ['January', 'March', 'June'].map(function (w) { return '<button type="button" data-parkuntil="' + w + '">' + w + '</button>'; }).join('')
        + '<input type="text" data-parkfree placeholder="or say what it waits for" autocomplete="off">'
        + '<button type="button" data-parkgo="1">park</button><button type="button" data-parkcancel="1">cancel</button>';
      $('.rb', row).appendChild(box);
      $$('[data-parkuntil]', box).forEach(function (b) { b.addEventListener('click', function () { act({ act: 'park', step: step, waiting_on: b.getAttribute('data-parkuntil') }); }); });
      var free = $('[data-parkfree]', box);
      function go() { var v = (free.value || '').trim(); if (!v) { receipt('A park carries its trigger — say until when, or what.', true); free.focus(); return; } act({ act: 'park', step: step, waiting_on: v }); }
      $('[data-parkgo]', box).addEventListener('click', go);
      free.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); go(); } if (e.key === 'Escape') closeParkPicks(); });
      $('[data-parkcancel]', box).addEventListener('click', closeParkPicks);
      free.focus();
    });
  });

  // ── add a task ──
  var addText = $('#addText'), addDate = $('#addDate'), addProj = $('#addProj'), addBtn = $('#addBtn');
  function add() {
    if (!addText || !addProj) return;
    var text = (addText.value || '').trim(); if (!text) { receipt('Say what the task is.', true); addText.focus(); return; }
    var when = parseDate(addDate ? addDate.value : '');
    if (when === null) { receipt('I could not read “' + addDate.value.trim() + '” as a date — Oct 3, Tuesday, today or 2026-10-03, or leave it blank.', true); return; }
    act({ act: 'add', initiative: addProj.value, kind: 'task', text: text, due: when === 'none' ? null : when });
  }
  if (addBtn) addBtn.addEventListener('click', add);
  if (addText) addText.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); add(); } });
  if (addDate) addDate.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); add(); } });

  // ── the tiles: Calendar (week / month), Email ──
  function tile(headId, bodyId, togId) {
    var head = $('#' + headId), body = $('#' + bodyId), tog = $('#' + togId); if (!head || !body) return;
    head.addEventListener('click', function () { var open = body.hidden; body.hidden = !open; head.closest('.tile').classList.toggle('open', open); if (tog) tog.textContent = open ? 'Close' : 'Open'; });
  }
  tile('calHead', 'calBody', 'calTog'); tile('mailHead', 'mailBody', 'mailTog');
  var calView = 'week', calMonth = 0;
  function drawCal() {
    var week = $('.calview.week'), months = $$('.calview.month'), lab = $('#calLab');
    $$('.caltab').forEach(function (b) { b.classList.toggle('on', b.getAttribute('data-cal') === calView); });
    if (week) week.hidden = calView !== 'week';
    months.forEach(function (m) { m.hidden = !(calView === 'month' && parseInt(m.getAttribute('data-month'), 10) === calMonth); });
    $$('[data-mo]').forEach(function (b) { b.hidden = calView !== 'month'; b.disabled = (b.getAttribute('data-mo') === '-1' && calMonth === 0) || (b.getAttribute('data-mo') === '1' && calMonth === months.length - 1); });
    if (lab && calView === 'month' && months[calMonth]) lab.textContent = months[calMonth].getAttribute('data-label') || '';
    if (lab && calView === 'week') lab.textContent = lab.getAttribute('data-week') || lab.textContent;
  }
  var lab0 = $('#calLab'); if (lab0) lab0.setAttribute('data-week', lab0.textContent);
  $$('.caltab').forEach(function (b) { b.addEventListener('click', function () { calView = b.getAttribute('data-cal'); drawCal(); }); });
  $$('[data-mo]').forEach(function (b) { b.addEventListener('click', function () { calMonth += parseInt(b.getAttribute('data-mo'), 10); drawCal(); }); });
  $$('[data-mail]').forEach(function (b) { b.addEventListener('click', function () { receipt(b.getAttribute('data-mail') === 'compose' ? 'Email is not connected — nothing can be composed yet.' : 'Connecting an account is not yet available — nothing was set up.', true); }); });

  // ── the tools ──
  $$('.tool[data-tool]').forEach(function (b) {
    b.addEventListener('click', function () {
      var k = b.getAttribute('data-tool');
      if (k === 'doctor') openWin('/doctor' + tokenQ());
      else if (k === 'zombie') openWin('/api/rnd/zombie_hunter_report' + tokenQ());
      else if (k === 'foundry') openWin('/foundry');
    });
  });

  // ── the composer: the effort's own say route ──
  var say = $('#say'), send = $('#sendBtn');
  function doSend() {
    var text = (say.value || '').trim(); if (!text || send.disabled) return;
    send.disabled = true; send.textContent = 'Thinking…';
    fetch('/api/steward/say', { method: 'POST', headers: headers(), body: JSON.stringify({ pid: PID, dir: '', text: text }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        send.disabled = false; send.textContent = 'Send';
        if (!j || j.ok === false) { receipt((j && (j.error || j.message)) || 'No answer came back — nothing was done.', true); return; }
        say.value = ''; receipt(j.say || j.reply || j.text || 'Said. The steward answers in the conversation; look again in a moment.');
      })
      .catch(function () { send.disabled = false; send.textContent = 'Send'; receipt('That did not go through — nothing was done.', true); });
  }
  if (send) send.addEventListener('click', doSend);
  if (say) say.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doSend(); } });
  applyFilter();
})();
