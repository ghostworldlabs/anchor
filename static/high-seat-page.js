/* The High Seat page (W1b, 2026-09-26): the page's own behaviour — the rail's destinations, the tiles that open
   and close, the cards that open a cockpit, the tools, the Add box, and the composer that talks to the steward
   through the existing say route. Nothing here invents data: every figure on the page was rendered from a record. */
(function () {
  'use strict';
  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  function token() { try { return localStorage.getItem('anchor_token') || ''; } catch (e) { return ''; } }
  // the hand-off the old dashboard did: /?token=<t> stores the token for this origin and drops it from the address
  try {
    var _qs = new URLSearchParams(location.search), _t = (_qs.get('token') || '').trim();
    if (_t) {
      _qs.delete('token'); var _rest = _qs.toString(); history.replaceState(null, '', location.pathname + (_rest ? '?' + _rest : '') + location.hash);
      login(_t);   // stored, and the browser logged in (the HttpOnly cookie the page routes and the card route accept), as the old home did — the one login()
    }
  } catch (e) {}
  function headers() {
    var h = { 'Content-Type': 'application/json' };
    var t = token(); if (t) { h['X-Anchor-Token'] = t; h['Authorization'] = 'Bearer ' + t; }   // the GET card route reads Authorization or the cookie
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
  try { var keptLine = sessionStorage.getItem('highseat_receipt'); if (keptLine) { var kl = JSON.parse(keptLine); receipt(kl.text, !!kl.bad, kl.undo); sessionStorage.removeItem('highseat_receipt'); } } catch (e) {}
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
  var DEST = { seat: '#brief', campaign: '#camp', active: '#shActive', week: '#shDated', desk: '#deskline',
               deck: '#shDeck', calendar: '#cal', email: '#cal', bench: '#shBench' };
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

  // W2c (2026-09-30, his three levels): the goals as a thin tile that expands (each goal a row that opens to its
  // components); Active and On deck as shelves of initiative cards; a drag out of a goal, between the shelves, up and
  // down inside one, or back onto the goals tile; the × sends one home; a registry project dropped on a goal becomes
  // its component. Every move is ONE act on the Campaign record with one line and undo; the page reloads to the
  // record as it stands, the receipt kept.
  var camp = $('#camp'), campTog = $('#campTog'), campHead = $('#campHead');
  function setCamp(open) { if (!camp) return; camp.classList.toggle('open', open); if (campTog) campTog.textContent = open ? 'Collapse' : 'Expand'; }
  if (campTog) campTog.addEventListener('click', function (e) { e.stopPropagation(); setCamp(!camp.classList.contains('open')); });
  if (campHead) campHead.addEventListener('click', function (e) { if (e.target.closest('a')) return; setCamp(!camp.classList.contains('open')); });
  $$('.grow .gh').forEach(function (h) { h.addEventListener('click', function (e) { if (e.target.closest('a, button')) return; h.parentNode.classList.toggle('open'); }); });
  var CAMPAIGN = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.campaign_pid) || '';
  var acting = false;
  function act(body) {   // one act in flight; the receipt and its undo survive the reload
    if (acting || !CAMPAIGN) return; acting = true; body.pid = CAMPAIGN;
    fetch('/api/high-seat/campaign', { method: 'POST', headers: headers(), body: JSON.stringify(body) })
      .then(function (r) { if (r.status === 401 || r.status === 403) { return { ok: false, receipt: NOT_LOGGED_IN }; } return r.json(); })
      .then(function (j) {
        if (!j || !j.ok) {
          acting = false;
          if (j && j.undo) {   // the act landed in part and the writer refused the rest: the receipt says so and its undo is his
            try { sessionStorage.setItem('highseat_receipt', JSON.stringify({ text: j.receipt || 'Refused.', bad: true, undo: j.undo })); } catch (e) {}
            location.reload(); return;
          }
          receipt((j && j.receipt) || 'Nothing was done.', true); return;
        }
        try { sessionStorage.setItem('highseat_receipt', JSON.stringify({ text: j.receipt, undo: j.undo || null })); } catch (e) {}
        location.reload();
      })
      .catch(function () { acting = false; receipt('That did not go through — nothing was done.', true); });
  }
  document.addEventListener('click', function (e) {
    var s = e.target.closest('[data-seat][data-step]');
    if (s) { e.preventDefault(); e.stopPropagation(); act({ act: 'seat', step: s.getAttribute('data-step'), seat: s.getAttribute('data-seat') }); return; }
    var h = e.target.closest('[data-home]');
    if (h) { e.preventDefault(); e.stopPropagation(); act({ act: 'home', step: h.getAttribute('data-home') }); }
  });
  // the drags: a card or a goal's initiative (data-step) onto a shelf — its place among the cards — or onto the goals
  // tile (home); a registry project (data-proj) onto a goal's row (a component of that goal)
  var drag = null;
  $$('[draggable="true"][data-step], [draggable="true"][data-proj]').forEach(function (el) {
    el.addEventListener('dragstart', function (e) {
      drag = { step: el.getAttribute('data-step') || '', proj: el.getAttribute('data-proj') || '', name: (el.getAttribute('data-name') || el.textContent || '').trim() };
      el.classList.add('dragging'); try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', drag.step || drag.proj); } catch (_) {}
    });
    el.addEventListener('dragend', function () { el.classList.remove('dragging'); $$('.over').forEach(function (z) { z.classList.remove('over'); }); drag = null; });
  });
  $$('.zone[data-seat]').forEach(function (z) {
    z.addEventListener('dragover', function (e) { if (!drag || !drag.step) return; e.preventDefault(); try { e.dataTransfer.dropEffect = 'move'; } catch (_) {} z.classList.add('over'); });
    z.addEventListener('dragleave', function (e) { if (!z.contains(e.relatedTarget)) z.classList.remove('over'); });
    z.addEventListener('drop', function (e) {
      e.preventDefault(); z.classList.remove('over'); if (!drag || !drag.step) return;
      var cards = $$('.grid > .tile', z).filter(function (c) { return c.getAttribute('data-step') !== drag.step; }), k = cards.length;
      for (var j = 0; j < cards.length; j++) { var b = cards[j].getBoundingClientRect(); if (e.clientY < b.top || (e.clientY <= b.bottom && e.clientX < b.left + b.width / 2)) { k = j; break; } }
      act({ act: 'seat', step: drag.step, seat: z.getAttribute('data-seat'), position: k });
    });
  });
  if (camp) {
    function seatedSource() { return !!(drag && drag.step && $('.tile[data-step="' + drag.step + '"], .irow.seated[data-step="' + drag.step + '"]')); }
    camp.addEventListener('dragover', function (e) {
      if (!drag) return; var g = e.target.closest('.grow');
      if (drag.proj ? false : !seatedSource()) return;   // an orphan may be dropped anywhere on the tile: a row adds it; the head answers with a line
      e.preventDefault(); try { e.dataTransfer.dropEffect = 'move'; } catch (_) {} (g || camp).classList.add('over');
    });
    camp.addEventListener('dragleave', function (e) { var g = e.target.closest('.grow'); if (g && !g.contains(e.relatedTarget)) g.classList.remove('over'); if (!camp.contains(e.relatedTarget)) camp.classList.remove('over'); });
    camp.addEventListener('drop', function (e) {
      e.preventDefault(); $$('.over').forEach(function (z) { z.classList.remove('over'); }); if (!drag) return;
      var g = e.target.closest('.grow');
      if (drag.proj) { if (g) act({ act: 'add', initiative: g.getAttribute('data-g'), kind: 'project', text: drag.name, project_id: drag.proj }); else receipt('Open the goals (Expand), then drop it on one goal.', true); return; }
      if (seatedSource()) act({ act: 'home', step: drag.step });
    });
  }

  // the Projects tile and its folders
  var ptile = $('#ptile'), ptileTog = $('#ptileTog');
  function setPtile(open) { if (!ptile) return; ptile.classList.toggle('open', open); if (ptileTog) ptileTog.textContent = open ? 'Hide' : 'Show all'; }
  var ptileToggle = $('#ptileToggle'); if (ptileToggle) ptileToggle.addEventListener('click', function () { setPtile(!ptile.classList.contains('open')); });
  // the old dashboard's list inside the tile: its folder heads and rows call these two by name (every folder starts closed)
  window.rndToggleFolder = function (head) {
    var f = head && head.closest('.rnd-folder'); if (!f) return;
    var closed = f.classList.toggle('rnd-collapsed');
    var tw = head.querySelector('.rnd-tw'); if (tw) tw.textContent = closed ? '\u25B8' : '\u25BE';   // the arrow turns, as the old page's does; nothing remembered
  };
  window.openProjectWindow = function (pid) { if (pid) openWin('/project/' + pid); };

  // the cards open in place (W2; the compact card, 2026-09-27): Status · Next steps · Deliverables · Plan in the acts
  // row — each part is composed on the server from the cockpit's own readers, so the card says what the cockpit says.
  // The GET card route reads the auth cookie or an Authorization header; a browser that never took the /?token=
  // hand-off has neither, the route answers 401, and the card SAYS so in words and asks for the token once, as the
  // old home did: store it, log the browser in (POST /api/auth/login mints the cookie), read the part again.
  var NOT_LOGGED_IN = 'This browser is not logged in to Anchor, so the record cannot be read.';
  var askedOnce = false;
  function login(t) {
    try { localStorage.setItem('anchor_token', t); } catch (e) {}
    return fetch('/api/auth/login', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-Anchor-Token': t }, body: JSON.stringify({ token: t }) }).catch(function () { return null; });
  }
  // R14 (2026-09-29): the token is pasted INTO the page (no window.prompt — a browser that suppresses dialogs showed
  // nothing). askToken() shows the box and answers false at once; a successful login reloads the page, which then
  // reads every card with the cookie. The box also opens on load when a token is required and none is held.
  var loginBox = $('#loginBox'), loginTok = $('#loginTok'), loginGo = $('#loginGo'), loginMsg = $('#loginMsg');
  function showLogin(text) {
    if (!loginBox) return;
    loginBox.hidden = false; if (loginMsg) loginMsg.textContent = text || '';
    try { loginBox.scrollIntoView({ block: 'center' }); } catch (e) {}
    setTimeout(function () { try { loginTok.focus(); } catch (e) {} }, 50);
  }
  function doLogin() {
    var t = ((loginTok && loginTok.value) || '').trim();
    if (!t) { if (loginMsg) loginMsg.textContent = 'Paste the token first.'; return; }
    if (loginGo) loginGo.disabled = true; if (loginMsg) loginMsg.textContent = 'Logging in\u2026';
    login(t).then(function (r) {
      if (loginGo) loginGo.disabled = false;
      if (r && r.ok) { if (loginMsg) loginMsg.textContent = 'Logged in.'; try { sessionStorage.setItem('highseat_receipt', JSON.stringify({ text: 'Logged in. This browser holds the token now.', undo: null })); } catch (e) {} location.reload(); return; }
      try { localStorage.removeItem('anchor_token'); } catch (e) {}
      if (loginMsg) loginMsg.textContent = (r && r.status === 401) ? 'That token was refused \u2014 it is not the current one.' : 'That did not go through; try again.';
    });
  }
  if (loginGo) loginGo.addEventListener('click', doLogin);
  if (loginTok) loginTok.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); doLogin(); } });
  // W2c-4 (his word, 2026-09-30): a browser the server already knows by its login cookie is logged in — no box, even with no token held here
  if (window.ANCHOR_BOOT && window.ANCHOR_BOOT.auth_required && !token() && !window.ANCHOR_BOOT.logged_in) showLogin('');
  // a held token may be the OLD one (after a rotation): check it once on load; a refusal opens the box at once
  if (window.ANCHOR_BOOT && window.ANCHOR_BOOT.auth_required && token()) {
    login(token()).then(function (r) {
      if (r && r.status === 401) { try { localStorage.removeItem('anchor_token'); } catch (e) {} showLogin('Your saved token is out of date — paste the current one.'); }
    });
  }
  function askToken() {
    showLogin('');
    return Promise.resolve(false);
  }
  function notLoggedIn() { return '<div class="cp-quiet cp-auth">' + NOT_LOGGED_IN + ' <button class="mini" data-login>paste the token</button></div>'; }
  function fetchPart(pid, part, dir, retried, open) {
    // W0 (2026-09-28): `open=1` only when a card's BODY opens — the presence writer's signal; a balloon's glance sends none
    return fetch('/api/high-seat/card?pid=' + encodeURIComponent(pid) + '&part=' + encodeURIComponent(part) + '&dir=' + encodeURIComponent(dir || '') + (open ? '&open=1' : ''), { headers: headers() })
      .then(function (r) {
        if (r.status === 401 || r.status === 403) {
          if (retried || askedOnce) return notLoggedIn();
          askedOnce = true;
          return askToken().then(function (ok) { return ok ? fetchPart(pid, part, dir, true) : notLoggedIn(); });
        }
        return r.json().then(function (jr) { return (jr && jr.html) || ('<div class="cp-quiet">' + ((jr && jr.error) || 'Nothing came back.') + '</div>'); });
      });
  }
  // W2e (2026-09-30, his words): the mark "ready for you" — a card whose wait he has not looked at pulses its edge;
  // opening any part of it is the look (kept in this browser, by the wait's own words: a new wait pulses again)
  function seen(card) { var tok = card.getAttribute('data-ready'); card.classList.remove('ready'); if (!tok) return; try { localStorage.setItem('hs_seen_' + card.id, tok); } catch (e) {} }
  $$('.tile[data-ready]').forEach(function (c) { var tok = c.getAttribute('data-ready'), was = ''; try { was = localStorage.getItem('hs_seen_' + c.id) || ''; } catch (e) {} if (was !== tok) c.classList.add('ready'); });
  function stopTalk(card) { if (card._talk && card._talk.stop) card._talk.stop(); card._talk = null; }
  // W2e-2 (2026-09-30, his word on the W2e preview): the tile OPENS to its decision brief — what waits on him, the
  // decision with the recommendation and one Accept, the material to review, the next step — and its dialogue, a
  // small window always there that grows to take the tile when a dialogue starts; the acts add a detail under the
  // brief. The dialogue is the same module the pages use, on THAT cockpit's stream; it stops when the tile closes.
  function talkHtml(id) {
    return '<div class="cdlg" id="' + id + '"><div class="exhead"><h3>this cockpit\u2019s steward</h3><span class="exstate" data-state="">\u2026</span><span class="note"></span></div>'
      + '<div class="scroll"><ul class="ex"><li class="exfade">Reading the conversation\u2026</li></ul></div>'
      + '<div class="composer"><textarea rows="2" placeholder="Ask this cockpit\u2019s steward, or tell it what to do \u2014 it answers here as it writes"></textarea>'
      + '<div class="comp-row"><span class="hint">Ctrl+Enter sends \u00b7 the same conversation as the cockpit</span><button class="send">Send</button></div></div></div>';
  }
  function grow(card) { var d = $('.cdlg', card); if (d) d.classList.add('big'); card.classList.add('talking'); }
  function startTalk(card, pid, dir) {
    var id = 'talk-' + card.id, list = $('#' + id + ' .ex'), box = $('#' + id + ' textarea'), sendBtn = $('#' + id + ' .send'), state = $('#' + id + ' .exstate');
    fetch('/api/steward/history?pid=' + encodeURIComponent(pid) + '&dir=' + encodeURIComponent(dir), { headers: window.StewardDialogue ? window.StewardDialogue.authHeaders(headers()) : headers() })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var ts = ((j && j.turns) || []).slice(-8); list.innerHTML = '';
        if (!ts.length) { list.innerHTML = '<li class="exfade">Nothing said in this cockpit yet.</li>'; return; }
        ts.forEach(function (t) {
          var you = ['john', 'you', 'user', 'human'].indexOf(String(t.role || '').toLowerCase()) >= 0;
          var li = document.createElement('li'); li.className = 'exrow ' + (you ? 'you' : 'st');
          li.innerHTML = '<div class="exw ' + (you ? 'you' : 'st') + '"><span class="w"></span></div><div class="ext"></div>';
          li.querySelector('.w').textContent = you ? 'You' : 'The steward'; li.querySelector('.ext').textContent = String(t.text || '').replace(/\s+/g, ' ').slice(0, 1600);
          list.appendChild(li);
        });
        list.scrollTop = list.scrollHeight; var sc = list.closest('.scroll'); if (sc) sc.scrollTop = sc.scrollHeight;
      })
      .catch(function () { list.innerHTML = '<li class="exfade">The conversation could not be read.</li>'; });
    var dlg = window.StewardDialogue ? window.StewardDialogue.init({ pid: pid, dir: dir, headers: headers, receipt: receipt, receiptKey: 'highseat_receipt', list: '#' + id + ' .ex', state: '#' + id + ' .exstate', steward: 'The steward', stamp: '' }) : null;
    card._talk = dlg;
    // a dialogue that starts — his send, or the steward at work — takes the tile
    if (state && window.MutationObserver) { var mo = new MutationObserver(function () { if (state.getAttribute('data-state') === 'busy') grow(card); }); mo.observe(state, { attributes: true, attributeFilter: ['data-state'] }); card._talkMo = mo; }
    function go() { var t = (box.value || '').trim(); if (!t || sendBtn.disabled || !dlg) return; grow(card); dlg.send(t, null, list, sendBtn, box, null); }
    sendBtn.addEventListener('click', go);
    box.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); go(); } });
  }
  function stopTalk(card) { if (card._talk && card._talk.stop) card._talk.stop(); card._talk = null; if (card._talkMo) { card._talkMo.disconnect(); card._talkMo = null; } }
  function openTile(card, pid, dir) {
    var body = $('.t-body', card);
    if (card.classList.contains('open')) return;
    $$('.tile.open').forEach(function (c) { if (c !== card) closeTile(c); });   // one tile open, one dialogue polling (Grok's read of W2e)
    card.classList.add('open'); card.classList.remove('talking'); body.hidden = false; seen(card);
    body.innerHTML = '<div class="cbrief"><div class="cp-quiet">Reading the record\u2026</div></div><div class="cdetail" hidden></div>' + talkHtml('talk-' + card.id);
    fetchPart(pid, 'brief', dir, false, true)
      .then(function (html) { var b = $('.cbrief', card); if (b && card.classList.contains('open')) { if (/^\s*<div class="cbrief/.test(html)) b.outerHTML = html; else b.innerHTML = html; } })   // the served brief IS the rectangle (never one cbrief inside another)
      .catch(function () { var b = $('.cbrief', card); if (b) b.innerHTML = '<div class="cp-quiet">That did not go through.</div>'; });
    startTalk(card, pid, dir);
  }
  function closeTile(card) {
    stopTalk(card); card.classList.remove('open', 'talking'); card.removeAttribute('data-open');
    var body = $('.t-body', card); if (body) { body.hidden = true; body.innerHTML = ''; }
    $$('.t-acts button.on, .t-eff-open.on', card).forEach(function (b) { b.classList.remove('on'); });
  }
  function openPart(card, pid, part, btn) {
    // W1/W2 (2026-09-28): a button may name ITS effort (another effort's wait; the head's pick) — its data-dir wins,
    // and the open state is keyed by part AND effort so the same part on another effort opens rather than closes
    var dir = (btn && btn.getAttribute && btn.getAttribute('data-dir') !== null) ? btn.getAttribute('data-dir') : (card.getAttribute('data-dir') || '');
    var key = part + '|' + dir;
    if (!card.classList.contains('open')) openTile(card, pid, card.getAttribute('data-dir') || '');
    var det = $('.cdetail', card);
    var same = card.getAttribute('data-open') === key;
    $$('.t-acts button, .t-eff-open', card).forEach(function (b) { b.classList.toggle('on', !same && b === btn); });
    if (same) { det.hidden = true; det.innerHTML = ''; card.removeAttribute('data-open'); return; }
    card.setAttribute('data-open', key); det.hidden = false; det.innerHTML = '<div class="cp-quiet">Reading the record\u2026</div>';
    fetchPart(pid, part, dir, false, false)
      .then(function (html) { if (card.getAttribute('data-open') === key) det.innerHTML = html; })
      .catch(function () { det.innerHTML = '<div class="cp-quiet">That did not go through.</div>'; });
  }
  $$('.tile[data-tile]').forEach(function (card) {
    var pid = card.getAttribute('data-tile');
    $$('[data-part]', card).forEach(function (b) {
      b.addEventListener('click', function (e) { e.stopPropagation(); openPart(card, pid, b.getAttribute('data-part'), b); });
    });
    card.addEventListener('click', function (e) {
      if (e.target.closest('a, button, .t-body')) return;
      if (card.classList.contains('open')) closeTile(card); else openTile(card, pid, card.getAttribute('data-dir') || '');   // the tile itself opens to its brief and its dialogue
    });
  });
  // W2e-3 (his word): the ask is a banner; a click opens the description and the recommendation; "talk about it" puts
  // the ask into the tile's dialogue and grows it
  document.addEventListener('click', function (e) {
    var a = e.target.closest('.cb-ask');
    if (a) { e.preventDefault(); e.stopPropagation(); var bd = a.parentNode.querySelector('.cb-body'); if (!bd) return; var open = bd.hidden; bd.hidden = !open; a.setAttribute('aria-expanded', open ? 'true' : 'false'); a.classList.toggle('open', open); return; }
    var t = e.target.closest('.cb-talk');
    if (t) { e.preventDefault(); e.stopPropagation(); var card = t.closest('.tile'), box = card && card.querySelector('.cdlg textarea'); if (!box) return; grow(card); box.value = 'About: ' + (t.getAttribute('data-ask') || '') + ' \u2014 '; box.focus(); try { box.setSelectionRange(box.value.length, box.value.length); } catch (err) {} }
  });
  // Accept in the brief: one click, the answer said to the steward as the cockpit says it, the dialogue takes the tile
  document.addEventListener('click', function (e) {
    var b = e.target.closest('.cb-accept'); if (!b) return;
    e.preventDefault(); e.stopPropagation();
    var card = b.closest('.tile'), pid = card && card.getAttribute('data-tile'), dir = (card && card.getAttribute('data-dir')) || '';
    if (!card || !pid) return;
    b.disabled = true; grow(card);
    fetch('/api/steward/say', { method: 'POST', headers: headers(), body: JSON.stringify({ pid: pid, dir: dir, text: 'Accept recommendation: ' + (b.getAttribute('data-rec') || ''), question_id: b.getAttribute('data-qid') || null }) })
      .then(function (r) { return r.json(); })
      .then(function (j) { if (!j || j.ok === false) { b.disabled = false; receipt((j && (j.error || j.say)) || 'That did not go through.', true); return; } b.textContent = 'Accepted'; receipt('Accepted \u2014 the steward answers in the tile as it writes.'); })
      .catch(function () { b.disabled = false; receipt('That did not go through.', true); });
  });
  // W2 (2026-09-28): the head's one act — "open" on the brief's lead opens THAT project's card on THAT effort
  document.addEventListener('click', function (e) {
    var h = e.target.closest('.h-open'); if (!h) return;
    e.preventDefault(); e.stopPropagation();
    var pid = h.getAttribute('data-pid') || '', card = document.getElementById('card-' + pid);
    if (!card) { window.open('/project/' + encodeURIComponent(pid), '_blank', 'noopener'); return; }
    card.scrollIntoView({ block: 'center', behavior: 'smooth' });
    card.removeAttribute('data-open');
    openPart(card, pid, h.getAttribute('data-part') || 'status', h);
  });
  // W4 (2026-09-28): his word on a proposed correction set — accept applies it, dismiss closes it; the part is read
  // again and the card's "proposed" line goes when no set is left open
  document.addEventListener('click', function (e) {
    var b = e.target.closest('.t-repair'); if (!b) return;
    e.preventDefault(); e.stopPropagation();
    var card = b.closest('.tile'), pid = b.getAttribute('data-pid') || '', dir = b.getAttribute('data-dir') || '';
    var body = { pid: pid, dir: dir, proposal_id: b.getAttribute('data-proposal') || '', disposition: b.getAttribute('data-disposition') || '' };
    $$('.t-repair', card || document).forEach(function (x) { x.disabled = true; });
    fetch('/api/high-seat/repair', { method: 'POST', headers: headers(), body: JSON.stringify(body) })
      .then(function (r) { if (r.status === 401 || r.status === 403) { return { ok: false, receipt: NOT_LOGGED_IN }; } return r.json(); })
      .then(function (j) {
        receipt((j && j.receipt) || 'That did not go through.', !(j && j.ok));
        if (!(j && j.ok)) { $$('.t-repair', card || document).forEach(function (x) { x.disabled = false; }); return; }
        if (card) {
          if (j.open === 0) { var pl = $('.t-line.prop', card); if (pl) pl.remove(); }   // exactly none open; an omitted count keeps the chip (Grok W4)
          var tb = $('.cdetail', card) || $('.t-body', card);   // W2e-2: the detail, never the whole tile (its dialogue stays)
          if (tb) fetchPart(pid, 'status', dir).then(function (html) { tb.hidden = false; tb.innerHTML = html; })
            .catch(function () { tb.innerHTML = '<div class="cp-quiet">The record changed, but this card did not refresh &mdash; reload the page.</div>'; });
        }
      })
      .catch(function () { receipt('That did not go through.', true); $$('.t-repair', card || document).forEach(function (x) { x.disabled = false; }); });
  });
  // "paste the token" on a card or a balloon that answered 401: ask again, then read that part again
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-login]'); if (!b) return;
    e.preventDefault(); e.stopPropagation();
    askToken().then(function (ok) {
      if (!ok) return;
      var bl = b.closest('.balloon');
      if (bl) {   // the balloon re-reads its own part into its body (Grok R7)
        var bb = $('.bl-body', bl); bb.innerHTML = '<div class="cp-quiet">Reading the record…</div>';
        fetchPart(bl.getAttribute('data-pid') || '', 'next', bl.getAttribute('data-dir') || '')
          .then(function (html) { if (bl.isConnected) bb.innerHTML = html; })
          .catch(function () { bb.innerHTML = '<div class="cp-quiet">That did not go through.</div>'; });
        return;
      }
      var card = b.closest('.tile'), key = card && card.getAttribute('data-open');
      if (!card || !key) return;
      var part = key.split('|')[0], odir = key.indexOf('|') >= 0 ? key.slice(key.indexOf('|') + 1) : null;
      card.removeAttribute('data-open');
      var again = odir !== null ? $('[data-part="' + part + '"][data-dir="' + odir.replace(/"/g, '') + '"]', card) : null;
      openPart(card, card.getAttribute('data-tile'), part, again || $('.t-acts [data-part="' + part + '"]', card));
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
      balloon.setAttribute('data-pid', pid);
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
      var ownCard = $('#card-' + pid), ownDir = ownCard ? (ownCard.getAttribute('data-dir') || '') : '';
      balloon.setAttribute('data-dir', ownDir);
      fetchPart(pid, 'next', ownDir)
        .then(function (html) { if (balloon) body.innerHTML = html; })
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

  // R11 (2026-09-28): New project — the old dashboard's folder-creation dialog ALONE, in a small window; it reports
  // back here when the project is made and this page reloads to show it in its folder
  var apNew = $('#apNew');
  if (apNew) apNew.addEventListener('click', function (e) {
    e.preventDefault(); e.stopPropagation();
    var w = null;
    try { w = window.open('/dashboard?new=1&only=1', 'anchor-new-project', 'width=640,height=800,resizable=yes,scrollbars=yes'); } catch (err) { w = null; }
    if (!w) receipt('The browser blocked the small window — allow popups and try again.', true);
  });
  window.addEventListener('message', function (ev) {
    if (ev.origin !== location.origin || !ev.data || ev.data.anchor !== 'project-created') return;
    var en = ev.data.entry || {};
    var text = ev.data.message || ('Project \u201c' + (en.name || '?') + '\u201d created' + (en.group ? ' in the folder ' + en.group : '') + '.');
    try { sessionStorage.setItem('highseat_receipt', JSON.stringify({ text: text, undo: null, bad: !!ev.data.group_error })); } catch (e) {}
    location.reload();
  });
  // R11: the steward's "start a new project" comes back as a project_create act — a confirm card under the
  // composer with the folder to put it in; nothing is created until Create it
  function projectCard(pc) {
    var old = $('#pcCard'); if (old) old.remove();
    var folder = String(pc.folder || ''), name = pc.name || folder.replace(/[\\\/]+$/, '').split(/[\\\/]/).pop();
    var groups = $('#apGroups'); var opts = groups ? groups.innerHTML : '<option value="">Ungrouped</option>';
    var card = document.createElement('div'); card.className = 'pc-card'; card.id = 'pcCard';
    card.innerHTML = '<div class="pc-q">Create <b></b> at <code></code>?</div>'
      + '<div class="pc-row"><label>Folder <select class="pc-group">' + opts + '</select></label>'
      + '<button class="mini pc-go">Create it</button><button class="mini pc-no">not now</button></div>';
    card.querySelector('b').textContent = name; card.querySelector('code').textContent = folder;
    var sel = card.querySelector('.pc-group');   // Ungrouped stays selected unless the act names a folder that exists
    if (pc.group && Array.prototype.some.call(sel.options, function (o) { return o.value === pc.group; })) sel.value = pc.group;
    var row = $('.comp-row'); if (row && row.parentNode) row.parentNode.insertBefore(card, row.nextSibling); else document.body.appendChild(card);
    card.querySelector('.pc-no').addEventListener('click', function () { card.remove(); });
    card.querySelector('.pc-go').addEventListener('click', function () {
      var go = card.querySelector('.pc-go'); go.disabled = true; go.textContent = 'Creating\u2026';
      fetch('/api/rnd/new_project', { method: 'POST', headers: headers(), body: JSON.stringify({ mode: 'auto', name: name, folder_path: folder, group: sel.value || '' }) })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (!d || !d.ok) { receipt('Not created: ' + ((d && (d.error || d.message)) || 'unknown'), true); go.disabled = false; go.textContent = 'Create it'; return; }
          var text = d.message || ('Project \u201c' + name + '\u201d created' + (sel.value ? ' in the folder ' + sel.value : '') + '.');
          try { sessionStorage.setItem('highseat_receipt', JSON.stringify({ text: text, undo: null, bad: !!d.group_error })); } catch (e) {}
          location.reload();
        })
        .catch(function () { receipt('That did not go through \u2014 nothing was created.', true); go.disabled = false; go.textContent = 'Create it'; });
    });
  }

  // the composer: the steward's say route (the same one the old home used)
  var say = $('#say'), send = $('#sendBtn');
  // R12 (2026-09-28, John): the unsent text is kept in this browser on every keystroke and put back after a crash,
  // a restart or a reload; a delivered turn clears it
  var DRAFT_KEY = 'anchor:draft:highseat', _draftT = null;
  function saveDraft() { try { if (say && say.value.trim()) localStorage.setItem(DRAFT_KEY, say.value); else localStorage.removeItem(DRAFT_KEY); } catch (e) {} }
  function clearDraft() { try { localStorage.removeItem(DRAFT_KEY); } catch (e) {} }
  if (say) {
    say.addEventListener('input', function () { clearTimeout(_draftT); _draftT = setTimeout(saveDraft, 250); });
    window.addEventListener('beforeunload', saveDraft);
    try { var keptDraft = localStorage.getItem(DRAFT_KEY); if (keptDraft && keptDraft.trim() && !say.value.trim()) { say.value = keptDraft; receipt('Your unsent text is back in the box.'); } } catch (e) {}
  }
  // the Seeds button opens the seed panel; a seed's button puts the steward's verb in the composer — Send is the word
  var seedBtn = $('#seedBtn'), seedPanel = $('#seedPanel');
  if (seedBtn && seedPanel) seedBtn.addEventListener('click', function () {
    var open = seedPanel.classList.toggle('open'); seedBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
  });
  $$('#seedPanel .go[data-seed-text]').forEach(function (g) {
    g.addEventListener('click', function () {
      if (!say) return;
      say.value = 'make ' + g.getAttribute('data-seed-text') + ' an initiative in tier 3';
      say.focus(); say.scrollIntoView({ behavior: 'smooth', block: 'center' });
      receipt('The verb is in the composer — add the tier or the life area if you want, then Send.');
    });
  });
  // W2c-2 (2026-09-30, his word: the dialogue must "engage the steward and then show the dialogue"): the composer is
  // ONE box. A Campaign verb and the new-project ask are answered by the High Seat's own route as before (a receipt,
  // the confirm card); anything else is said to the Campaign's steward — the Desk — and the exchange shows below, live
  var dlg = (window.StewardDialogue && CAMPAIGN) ? window.StewardDialogue.init({
    pid: CAMPAIGN, dir: '', headers: headers, receipt: receipt, receiptKey: 'highseat_receipt',
    steward: (window.ANCHOR_BOOT && window.ANCHOR_BOOT.steward) || 'The steward', stamp: (window.ANCHOR_BOOT && window.ANCHOR_BOOT.stamp) || '',
    goalName: function (id) { var g = $('.grow[data-g="' + id + '"] .gn'); return (g && g.textContent.trim()) || id; },
    openGoal: function (id) { window.open('/project/' + encodeURIComponent(CAMPAIGN) + '?open=' + encodeURIComponent(id), '_blank', 'noopener'); },   // the goal's place, as the rendered chip opens it (Grok W2c-2)
    onAuth: function () { showLogin('The steward’s words cannot reach this page until this browser is logged in.'); }
  }) : null;
  function doSend() {
    var text = (say.value || '').trim(); if (!text || send.disabled) return;
    send.disabled = true; send.textContent = 'Thinking…';
    fetch('/api/ecgberht/high_seat_say', { method: 'POST', headers: headers(), body: JSON.stringify({ text: text, verbs_only: !!dlg }) })
      .then(function (r) { return r.json(); })
      .then(function (j) {
        send.disabled = false; send.textContent = 'Send';
        if (j && j.ok && j.talk && dlg) { dlg.send(text, null, dlg.mainList(), send, say, DRAFT_KEY); return; }   // not a verb: the steward, in the dialogue
        if (!j || !j.ok) { receipt((j && (j.say || j.message || j.error)) || 'No answer came back — nothing was done.', true); return; }
        say.value = ''; clearDraft(); receipt(j.say || '…', false, j.undo || null);
        if (j.campaign_act && !j.read_only) {   // the Campaign tile shows the change after the reload; the line and its undo survive it
          try { sessionStorage.setItem('highseat_receipt', JSON.stringify({ text: j.say, undo: j.undo || null })); } catch (e) {}
          setTimeout(function () { location.reload(); }, 900); return;
        }
        if (j.project_create && j.project_create.folder) projectCard(j.project_create);   // R11: the card is here, not on the old dashboard
      })
      .catch(function () { send.disabled = false; send.textContent = 'Send'; receipt('That did not go through — nothing was done.', true); });
  }
  if (send) send.addEventListener('click', doSend);
  if (say) say.addEventListener('keydown', function (e) { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); doSend(); } });

  // a redeploy reloads the open page, as the old home did (the verification law: a mechanism, not "refresh"): /api/version
  // every 30 s; a build other than the one this page booted with reloads it once — never while he is typing
  (function () {
    var mine = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.build_id) || '';
    if (!mine) return;
    // W2c-4: never while he types — a key in the last ten seconds; a box that merely holds a draft no longer pins a stale page (the draft is put back after the reload)
    var lastKey = 0; document.addEventListener('keydown', function () { lastKey = Date.now(); });
    function typing() { return Date.now() - lastKey < 10000; }
    setInterval(function () {
      fetch('/api/version', { cache: 'no-store' }).then(function (r) { return r.json(); }).then(function (d) {
        var v = d && d.version; if (!v || v === mine || typing()) return;
        try { if (sessionStorage.getItem('highseat_reloaded_for') === String(v)) return; sessionStorage.setItem('highseat_reloaded_for', String(v)); } catch (e) {}
        location.reload();
      }).catch(function () {});
    }, 30000);
  })();
})();
