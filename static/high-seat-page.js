/* The High Seat page (W1b, 2026-09-26): the page's own behaviour — the rail's destinations, the tiles that open
   and close, the cards that open a cockpit, the tools, the Add box, and the composer that talks to the steward
   through the existing say route. Nothing here invents data: every figure on the page was rendered from a record. */
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
  function openWin(url) {
    var w = null;
    try { w = window.open('about:blank', '_blank'); } catch (e) { w = null; }
    if (!w || w === window) { receipt('The browser blocked the new window — allow popups and try again.', true); return; }
    try { w.opener = null; w.location.replace(url); w.focus(); } catch (e) { try { w.close(); } catch (_) {} }
  }
  var lastUndo = null;
  function receipt(text, bad, undo) {
    var r = $('#receipt'), t = $('#receiptText'); if (!r || !t) return;
    lastUndo = undo || null; var u = $('#undoBtn'); if (u) u.hidden = !undo;
    t.textContent = text; r.hidden = false; r.classList.toggle('bad', !!bad);
  }
  try { var keptLine = sessionStorage.getItem('highseat_receipt'); if (keptLine) { var kl = JSON.parse(keptLine); receipt(kl.text, false, kl.undo); sessionStorage.removeItem('highseat_receipt'); } } catch (e) {}
  var undoBtn = $('#undoBtn');
  if (undoBtn) undoBtn.addEventListener('click', function () {
    if (!lastUndo) return;
    var body = JSON.parse(JSON.stringify(lastUndo)); body.pid = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.campaign_pid) || '';
    undoBtn.disabled = true;
    fetch('/api/high-seat/campaign', { method: 'POST', headers: headers(), body: JSON.stringify(body) })
      .then(function (r) { return r.json(); })
      .then(function (j) { undoBtn.disabled = false; if (!j || !j.ok) { receipt((j && j.receipt) || 'Nothing was undone.', true); return; }
        try { sessionStorage.setItem('highseat_receipt', JSON.stringify({ text: j.receipt, undo: j.undo || null })); } catch (e) {}
        location.reload(); })
      .catch(function () { undoBtn.disabled = false; receipt('That did not go through — nothing was undone.', true); });
  });

  // the rail: each destination scrolls to its section and opens it
  var DEST = { seat: '#brief', campaign: '#camp', needs: '#shNeeds', week: '#shDated', desk: '#deskline',
               parked: '#shPark', calendar: '#cal', email: '#cal', bench: '#shBench' };
  $$('#railNav button').forEach(function (b) {
    b.addEventListener('click', function () {
      var key = b.getAttribute('data-rail'), sel = DEST[key], el = sel && $(sel);
      $$('#railNav button').forEach(function (x) { x.classList.toggle('on', x === b); });
      if (!el) return;
      if (key === 'campaign') $('#camp') && $('#camp').classList.add('open');
      if (key === 'calendar' || key === 'email') { $('#cal') && $('#cal').classList.add('open'); setCalTab(key === 'email' ? 'mail' : 'cal'); }
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
  });

  // the Campaign tile: Show Tier 1 / Hide; a Tier 1 tile opens to its parts, one at a time
  var camp = $('#camp'), campTog = $('#campTog'), campHead = $('#campHead');
  function setCamp(open) { if (!camp) return; camp.classList.toggle('open', open); if (campTog) campTog.textContent = open ? 'Hide' : 'Show Tier 1'; }
  if (campTog) campTog.addEventListener('click', function (e) { e.stopPropagation(); setCamp(!camp.classList.contains('open')); });
  if (campHead) campHead.addEventListener('click', function (e) { if (e.target.closest('a')) return; setCamp(!camp.classList.contains('open')); });
  $$('.ini-tile').forEach(function (tile) {
    tile.addEventListener('click', function (e) {
      if (e.target.closest('a')) return;
      var was = tile.classList.contains('open');
      $$('.ini-tile').forEach(function (t) { t.classList.remove('open'); });
      if (!was) tile.classList.add('open');
    });
  });

  // the Projects tile and its folders
  var ptile = $('#ptile'), ptileTog = $('#ptileTog');
  function setPtile(open) { if (!ptile) return; ptile.classList.toggle('open', open); if (ptileTog) ptileTog.textContent = open ? 'Hide' : 'Show all'; }
  var ptileToggle = $('#ptileToggle'); if (ptileToggle) ptileToggle.addEventListener('click', function () { setPtile(!ptile.classList.contains('open')); });
  $$('.fold-h').forEach(function (h) { h.addEventListener('click', function () { h.parentElement.classList.toggle('open'); }); });
  $$('.prow .go').forEach(function (g) {
    g.addEventListener('click', function (e) {
      e.stopPropagation();
      var card = $('#card-' + g.getAttribute('data-goto'));
      if (card) { card.scrollIntoView({ behavior: 'smooth', block: 'center' }); card.classList.add('flash'); setTimeout(function () { card.classList.remove('flash'); }, 1600); }
    });
  });
  $$('.prow').forEach(function (row) {
    row.addEventListener('dblclick', function () { var pid = row.getAttribute('data-pid'); if (pid) openWin('/project/' + pid); });
  });

  // the cards open in place (W2): Status beside the name; Next steps · Deliverables · Plan in the acts row —
  // each part is composed on the server from the cockpit's own readers, so the card says what the cockpit says
  function openPart(card, pid, part, btn) {
    var body = $('.t-body', card);
    var same = card.getAttribute('data-open') === part;
    $$('.t-acts button, .statusbtn', card).forEach(function (b) { b.classList.toggle('on', !same && b === btn); });
    if (same) { body.hidden = true; card.removeAttribute('data-open'); card.classList.remove('open'); return; }
    card.setAttribute('data-open', part); card.classList.add('open');
    body.hidden = false; body.innerHTML = '<div class="cp-quiet">Reading the record…</div>';
    fetch('/api/high-seat/card?pid=' + encodeURIComponent(pid) + '&part=' + encodeURIComponent(part), { headers: headers() })
      .then(function (r) { return r.json(); })
      .then(function (jr) {
        var html = (jr && jr.html) || ('<div class="cp-quiet">' + ((jr && jr.error) || 'Nothing came back.') + '</div>');
        if (card.getAttribute('data-open') === part) body.innerHTML = html;
      })
      .catch(function () { body.innerHTML = '<div class="cp-quiet">That did not go through.</div>'; });
  }
  $$('.tile[data-tile]').forEach(function (card) {
    var pid = card.getAttribute('data-tile');
    $$('[data-part]', card).forEach(function (b) {
      b.addEventListener('click', function (e) { e.stopPropagation(); openPart(card, pid, b.getAttribute('data-part'), b); });
    });
    card.addEventListener('click', function (e) {
      if (e.target.closest('a, button, .t-body')) return;
      openPart(card, pid, 'status', $('.statusbtn', card));
    });
  });

  // the ruler's markers balloon open (W2): the step, its project and date, the project's open decision and
  // what it depends on — the same Next steps fragment a card shows — and the links into the cockpit
  var balloon = null;
  function closeBalloon() { if (balloon) { balloon.remove(); balloon = null; } $$('.mkcard.on').forEach(function (m) { m.classList.remove('on'); }); }
  document.addEventListener('click', function (e) { if (balloon && !e.target.closest('.balloon, .mkcard')) closeBalloon(); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape') closeBalloon(); });
  $$('.mkcard').forEach(function (mk) {
    mk.addEventListener('click', function (e) {
      e.preventDefault(); e.stopPropagation();
      if (mk.classList.contains('on')) { closeBalloon(); return; }
      closeBalloon(); mk.classList.add('on');
      var pid = (mk.getAttribute('href') || '').replace('/project/', '');
      var ruler = $('#ruler');
      balloon = document.createElement('div'); balloon.className = 'balloon';
      var r = mk.getBoundingClientRect(), rr = ruler.getBoundingClientRect();
      var left = Math.max(8, Math.min(r.left - rr.left, rr.width - 440));
      balloon.style.left = left + 'px'; balloon.style.top = (r.bottom - rr.top + 8) + 'px';
      balloon.style.setProperty('--arrow', Math.max(12, r.left - rr.left - left + 20) + 'px');
      balloon.innerHTML = '<div class="bl-head"><b>' + mk.querySelector('.mk-what').textContent + '</b> · ' + mk.querySelector('.mk-date').textContent
        + ' · ' + mk.querySelector('.mk-proj').textContent + '</div><div class="bl-body"><div class="cp-quiet">Reading the record…</div></div>'
        + '<div class="bl-foot"><a href="#card-' + pid + '" data-bl-card="' + pid + '">its card</a> <span class="bl-close" data-bl-close>close</span></div>';
      ruler.appendChild(balloon);
      $('[data-bl-close]', balloon).addEventListener('click', closeBalloon);
      var cardLink = $('[data-bl-card]', balloon);
      cardLink.addEventListener('click', function (ev) { ev.preventDefault(); var c = $('#card-' + pid); closeBalloon(); if (c) { c.scrollIntoView({ behavior: 'smooth', block: 'center' }); c.classList.add('flash'); setTimeout(function () { c.classList.remove('flash'); }, 1600); } });
      var body = $('.bl-body', balloon);
      fetch('/api/high-seat/card?pid=' + encodeURIComponent(pid) + '&part=next', { headers: headers() })
        .then(function (rs) { return rs.json(); })
        .then(function (jr) { var html = (jr && jr.html) || '<div class="cp-quiet">' + ((jr && jr.error) || 'Nothing came back.') + '</div>'; if (balloon) body.innerHTML = html; })
        .catch(function () { if (balloon) body.innerHTML = '<div class="cp-quiet">That did not go through.</div>'; });
    });
  });

  // the Calendar / Email tile
  var cal = $('#cal'), calTog = $('#calTog');
  function setCalTab(which) { var a = $('#tabCal'), b = $('#tabMail'); if (a) a.classList.toggle('on', which === 'cal'); if (b) b.classList.toggle('on', which === 'mail'); }
  var calHead = $('#calHead'); if (calHead) calHead.addEventListener('click', function (e) {
    var tab = e.target.closest('.cal-tab');
    if (tab) { setCalTab(tab.id === 'tabMail' ? 'mail' : 'cal'); cal.classList.add('open'); }
    else cal.classList.toggle('open');
    if (calTog) calTog.textContent = cal.classList.contains('open') ? 'Close' : 'Open';
  });
  $$('.dchip[data-desk]').forEach(function (c) {
    c.addEventListener('click', function () {
      var k = c.getAttribute('data-desk');
      if (k === 'tasks') { openWin('/dashboard#tile-tasks'); }
      else { cal && cal.classList.add('open'); setCalTab(k === 'mail' ? 'mail' : 'cal'); cal && cal.scrollIntoView({ behavior: 'smooth', block: 'start' }); }
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

  // Add a project: nothing is written from this page — the old dashboard makes and confirms a project
  var apCreate = $('#apCreate');
  if (apCreate) apCreate.addEventListener('click', function (e) {
    e.preventDefault();
    var name = ($('#apName').value || '').trim();
    openWin('/dashboard' + (name ? ('#new-project=' + encodeURIComponent(name)) : ''));
  });

  // the composer: the steward's say route (the same one the old home used)
  var say = $('#say'), send = $('#sendBtn');
  function doSend() {
    var text = (say.value || '').trim(); if (!text || send.disabled) return;
    send.disabled = true; send.textContent = 'Thinking…';
    fetch('/api/ecgberht/high_seat_say', { method: 'POST', headers: headers(), body: JSON.stringify({ text: text }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        send.disabled = false; send.textContent = 'Send';
        if (!j || !j.ok) { receipt((j && (j.say || j.message || j.error)) || 'No answer came back — nothing was done.', true); return; }
        say.value = ''; receipt(j.say || '…', false, j.undo || null);
        if (j.campaign_act && !j.read_only) {   // the Campaign tile shows the change after the reload; the line and its undo survive it
          try { sessionStorage.setItem('highseat_receipt', JSON.stringify({ text: j.say, undo: j.undo || null })); } catch (e) {}
          setTimeout(function () { location.reload(); }, 900); return;
        }
        if (j.project_create && j.project_create.folder) receipt((j.say ? j.say + ' ' : '') + 'A project card is ready: ' + j.project_create.folder + ' — confirm it on the old dashboard.');
      })
      .catch(function () { send.disabled = false; send.textContent = 'Send'; receipt('That did not go through — nothing was done.', true); });
  }
  if (send) send.addEventListener('click', doSend);
  if (say) say.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doSend(); } });
})();
