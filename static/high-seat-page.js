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
  function receipt(text, bad) {
    var r = $('#receipt'), t = $('#receiptText'); if (!r || !t) return;
    t.textContent = text; r.hidden = false; r.classList.toggle('bad', !!bad);
  }

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
  var partCache = {};
  function openPart(card, pid, part, btn) {
    var body = $('.t-body', card);
    var same = card.getAttribute('data-open') === part;
    $$('.t-acts button, .statusbtn', card).forEach(function (b) { b.classList.toggle('on', !same && b === btn); });
    if (same) { body.hidden = true; card.removeAttribute('data-open'); card.classList.remove('open'); return; }
    card.setAttribute('data-open', part); card.classList.add('open');
    body.hidden = false; body.innerHTML = '<div class="cp-quiet">Reading the record…</div>';
    var key = pid + ':' + part;
    if (partCache[key]) { body.innerHTML = partCache[key]; return; }
    fetch('/api/high-seat/card?pid=' + encodeURIComponent(pid) + '&part=' + encodeURIComponent(part), { headers: headers() })
      .then(function (r) { return r.json(); })
      .then(function (jr) {
        var html = (jr && jr.html) || ('<div class="cp-quiet">' + ((jr && jr.error) || 'Nothing came back.') + '</div>');
        partCache[key] = html; if (card.getAttribute('data-open') === part) body.innerHTML = html;
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

  // Add a project: the existing route, new-folder mode; the row appears on the next look
  var apCreate = $('#apCreate');
  if (apCreate) apCreate.addEventListener('click', function () {
    var name = ($('#apName').value || '').trim(), parent = ($('#apParent').value || '').trim(), hint = $('#apHint');
    if (!name || !parent) { hint.textContent = 'A name and a parent folder are needed.'; return; }
    apCreate.disabled = true; hint.textContent = 'Creating…';
    fetch('/api/rnd/new_project', { method: 'POST', headers: headers(), body: JSON.stringify({ mode: 'new_folder', name: name, parent_path: parent, priority: 2 }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        apCreate.disabled = false;
        if (!j || !j.ok || !j.entry) { hint.textContent = (j && (j.error || j.message)) || 'Nothing was created.'; return; }
        hint.textContent = 'Created ' + (j.entry.name || name) + ' — look again to see its row; opening its cockpit.';
        openWin('/project/' + j.entry.id);
        setTimeout(function () { location.reload(); }, 1200);
      })
      .catch(function () { apCreate.disabled = false; hint.textContent = 'That did not go through — nothing was created.'; });
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
        say.value = ''; receipt(j.say || '…');
        if (j.project_create && j.project_create.folder) receipt((j.say ? j.say + ' ' : '') + 'A project card is ready: ' + j.project_create.folder + ' — confirm it on the old dashboard until this page carries the card (W5).');
      })
      .catch(function () { send.disabled = false; send.textContent = 'Send'; receipt('That did not go through — nothing was done.', true); });
  }
  if (send) send.addEventListener('click', doSend);
  if (say) say.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doSend(); } });
})();
