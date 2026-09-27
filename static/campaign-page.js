/* The Campaign page (W3c, 2026-09-26): the view toggle, the tiles and lanes that open, the area filter, and every act
   on the record through /api/high-seat/campaign — each act a receipt with undo; the composer talks to the steward
   through the effort's own say route. Nothing here invents data: the page was rendered from the record. */
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

  function act(body, onDone) {
    body.pid = PID;
    fetch('/api/high-seat/campaign', { method: 'POST', headers: headers(), body: JSON.stringify(body) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        if (!j || !j.ok) { receipt((j && j.receipt) || 'Nothing was done.', true); return; }
        try { sessionStorage.setItem('campaign_receipt', JSON.stringify({ text: j.receipt, bad: false, undo: j.undo || null })); } catch (e) {}
        if (onDone) onDone(j); else location.reload();
      })
      .catch(function () { receipt('That did not go through — nothing was done.', true); });
  }
  var undoBtn = $('#undoBtn');
  if (undoBtn) undoBtn.addEventListener('click', function () { if (lastUndo) act(lastUndo); });

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

  // tiles: one open at a time in the grouped view; lanes open independently
  function openTile(id) {
    $$('.itile').forEach(function (t) { t.classList.toggle('open', t.getAttribute('data-lane') === id && !t.classList.contains('open')); });
    if (grouped) grouped.classList.toggle('focused', !!$('.itile.open'));
  }
  $$('.itile [data-act="toggle"]').forEach(function (b) { b.addEventListener('click', function () { openTile(b.getAttribute('data-lane')); }); });
  $$('.lane [data-act="toggle"]').forEach(function (b) { b.addEventListener('click', function () { var l = b.closest('.lane'); l.classList.toggle('open'); }); });
  $$('.pc[data-act="chip"]').forEach(function (c) { c.addEventListener('click', function () { setView('grouped'); openTile(c.getAttribute('data-lane')); var row = $('.row[data-part="' + c.getAttribute('data-part') + '"]'); if (row) { row.scrollIntoView({ block: 'center' }); row.classList.add('hot'); setTimeout(function () { row.classList.remove('hot'); }, 1600); } }); });
  var closeAll = $('#closeAll'); if (closeAll) closeAll.addEventListener('click', function () { $$('.itile.open, .lane.open').forEach(function (t) { t.classList.remove('open'); }); if (grouped) grouped.classList.remove('focused'); });
  $$('[data-goto]').forEach(function (g) { g.addEventListener('click', function () { setView('grouped'); openTile(g.getAttribute('data-goto')); var t = $('.itile[data-lane="' + g.getAttribute('data-goto') + '"]'); if (t) t.scrollIntoView({ block: 'center' }); }); });

  // the area filter: dims, never removes, so the numbers stay true
  $$('.ac[data-area]').forEach(function (b) {
    b.addEventListener('click', function () {
      var a = b.getAttribute('data-area'), was = b.classList.contains('on');
      $$('.ac').forEach(function (x) { x.classList.remove('on'); });
      $$('.itile, .lane').forEach(function (t) { t.classList.remove('dimmed'); });
      if (!was) { b.classList.add('on'); $$('.itile, .lane').forEach(function (t) { if ((t.querySelector('.larea') || {}).textContent.trim().toLowerCase() !== a) t.classList.add('dimmed'); }); }
    });
  });

  // ranks and tiers
  $$('[data-act="up"], [data-act="down"]').forEach(function (b) { b.addEventListener('click', function () { act({ act: 'rank', step: b.getAttribute('data-lane'), direction: b.getAttribute('data-act') }); }); });
  $$('.tsel[data-tiersel]').forEach(function (s) { s.addEventListener('change', function () { act({ act: 'move_tier', step: s.getAttribute('data-tiersel'), tier: s.value }); }); });

  // parts: rename, date, flag, park, tick, order
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
  $$('[data-act="park"]').forEach(function (p) { p.addEventListener('click', function () { var v = window.prompt('Park until when, or what? (the trigger)', 'January'); if (v === null || !v.trim()) return; act({ act: 'park', step: p.getAttribute('data-part'), waiting_on: v.trim() }); }); });
  $$('[data-act="unpark"]').forEach(function (p) { p.addEventListener('click', function () { act({ act: 'unpark', step: p.getAttribute('data-part') }); }); });
  $$('[data-act="flag"]').forEach(function (p) { p.addEventListener('click', function () { act({ act: 'flag', step: p.getAttribute('data-part') }); }); });
  $$('[data-act="unflag"]').forEach(function (p) { p.addEventListener('click', function () { act({ act: 'unflag', step: p.getAttribute('data-part') }); }); });
  $$('[data-act="tick"]').forEach(function (p) { p.addEventListener('click', function () { if (p.disabled) return; act({ act: 'tick', step: p.getAttribute('data-part') }); }); });
  $$('[data-act="pup"], [data-act="pdown"]').forEach(function (p) { p.addEventListener('click', function () { receipt('Ordering parts inside an initiative is not built yet — the initiative order and the tiers are.', true); }); });

  // add a part
  $$('.addline').forEach(function (line) {
    var kind = $('[data-add="kind"]', line), text = $('[data-add="text"]', line), proj = $('[data-add="project"]', line), date = $('[data-add="date"]', line), btn = $('[data-act="add"]', line);
    function sync() { var isP = kind.value === 'project'; proj.style.display = isP ? '' : 'none'; text.placeholder = isP ? 'a name for the part (optional)' : 'Add a part'; }
    kind.addEventListener('change', sync); sync();
    function go() { act({ act: 'add', initiative: btn.getAttribute('data-lane'), kind: kind.value, text: text.value, due: date.value.trim() || null, project_id: proj.value || null }); }
    btn.addEventListener('click', go);
    text.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); go(); } });
  });

  // seeds → initiatives: the two questions, both skippable
  $$('[data-act="promote"]').forEach(function (b) {
    b.addEventListener('click', function () {
      var seed = b.closest('.seed'), text = $('.st', seed).textContent.trim();
      var tier = window.prompt('Which tier? 1 · do first, 2 · next in line, 3 · when there is room (blank = 3)', '3'); if (tier === null) return;
      var area = window.prompt('Which life area? family · professional · writing · research · tools · personal (blank = none yet)', ''); if (area === null) return;
      act({ act: 'promote', seed: text, tier: tier.trim() || '3', area: area.trim().toLowerCase() || null });
    });
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
})();
