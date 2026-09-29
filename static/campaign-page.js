/* The Campaign page (W3c, 2026-09-26; trimmed by its Rabbit read): the view toggle, the tiles and lanes that open,
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
        if (!j || !j.ok) { busy = false; receipt((j && j.receipt) || 'Nothing was done.', true); return; }
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

  // tiles: one open at a time in the grouped view; lanes open independently
  function openTile(id) {
    $$('.itile').forEach(function (t) { t.classList.toggle('open', t.getAttribute('data-lane') === id && !t.classList.contains('open')); });
  }
  $$('.itile [data-act="toggle"]').forEach(function (b) { b.addEventListener('click', function () { openTile(b.getAttribute('data-lane')); }); });
  $$('.lane [data-act="toggle"]').forEach(function (b) { b.addEventListener('click', function () { var l = b.closest('.lane'); l.classList.toggle('open'); }); });
  $$('.pc[data-act="chip"]').forEach(function (c) { c.addEventListener('click', function () { setView('grouped'); openTile(c.getAttribute('data-lane')); var row = $('.row[data-part="' + c.getAttribute('data-part') + '"]'); if (row) { row.scrollIntoView({ block: 'center' }); row.classList.add('hot'); setTimeout(function () { row.classList.remove('hot'); }, 1600); } }); });
  var closeAll = $('#closeAll'); if (closeAll) closeAll.addEventListener('click', function () { $$('.itile.open, .lane.open').forEach(function (t) { t.classList.remove('open'); }); });
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

  // W2 of the active set (2026-09-29, C1): the goals band's rows drag - between Active and the bench, and up and
  // down inside Active; every drop is ONE act through the same route, with undo. The bench keeps its own order
  // (by nearest date), so a drop there only benches. Nothing moves on the page until the record says so.
  var dragId = null, dragFrom = null;
  function rowsOf(list) { return $$('.grow[draggable]', list); }
  function clearMarks() { $$('.grow.over-before, .grow.over-after').forEach(function (r) { r.classList.remove('over-before', 'over-after'); }); $$('.glist.over').forEach(function (l) { l.classList.remove('over'); }); }
  function indexAt(list, y) {   // where the dragged row would land: before the first row whose middle is below the pointer
    var rows = rowsOf(list).filter(function (r) { return r.getAttribute('data-init') !== dragId; }), k = rows.length;
    for (var i = 0; i < rows.length; i++) { var b = rows[i].getBoundingClientRect(); if (y < b.top + b.height / 2) { k = i; break; } }
    return { k: k, rows: rows };
  }
  $$('.grow[draggable]').forEach(function (r) {
    r.addEventListener('dragstart', function (e) {
      dragId = r.getAttribute('data-init'); dragFrom = r.getAttribute('data-list'); r.classList.add('dragging');
      try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', dragId); } catch (_) {}
    });
    r.addEventListener('dragend', function () { r.classList.remove('dragging'); clearMarks(); dragId = null; dragFrom = null; });
  });
  $$('.glist').forEach(function (list) {
    list.addEventListener('dragover', function (e) {
      if (!dragId) return;
      e.preventDefault(); try { e.dataTransfer.dropEffect = 'move'; } catch (_) {}
      clearMarks(); list.classList.add('over');
      if (list.getAttribute('data-list') !== 'active') return;
      var at = indexAt(list, e.clientY);
      if (at.rows.length) { if (at.k < at.rows.length) at.rows[at.k].classList.add('over-before'); else at.rows[at.rows.length - 1].classList.add('over-after'); }
    });
    list.addEventListener('dragleave', function (e) { if (!list.contains(e.relatedTarget)) clearMarks(); });
    list.addEventListener('drop', function (e) {
      if (!dragId) return;
      e.preventDefault();
      var to = list.getAttribute('data-list'), id = dragId, from = dragFrom; clearMarks();
      if (to === 'bench') { if (from === 'active') act({ act: 'bench', step: id }); return; }
      var k = indexAt(list, e.clientY).k;
      if (from === 'active') {
        var was = rowsOf(list).map(function (r) { return r.getAttribute('data-init'); }).indexOf(id);
        if (was !== k) act({ act: 'order', step: id, position: k });
      } else act({ act: 'activate', step: id, order: k });
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
    send.disabled = true; send.textContent = 'Thinking…';
    fetch('/api/steward/say', { method: 'POST', headers: headers(), body: JSON.stringify({ pid: PID, dir: '', text: text }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        send.disabled = false; send.textContent = 'Send';
        if (!j || j.ok === false) { receipt((j && (j.say || j.receipt || j.error || j.message)) || 'No answer came back — nothing was done.', true); return; }
        clearDraft();
        if (j.campaign_act && !j.read_only) {   // a Campaign verb: the record changed; the receipt and its undo survive the reload
          try { sessionStorage.setItem('campaign_receipt', JSON.stringify({ text: j.say, bad: false, undo: j.undo || null })); } catch (e) {}
          location.reload(); return;
        }
        say.value = ''; receipt(j.say || j.reply || j.text || 'Said. The steward answers in the conversation; look again in a moment.');
      })
      .catch(function () { send.disabled = false; send.textContent = 'Send'; receipt('That did not go through — nothing was done.', true); });
  }
  if (send) send.addEventListener('click', doSend);
  if (say) say.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doSend(); } });
})();
