/* The steward's dialogue (W2b-1/W2b-3 on the Campaign page, 2026-09-30; W2c-2 the same day for the High Seat too, his
   word: both dialogues "need to engage the steward and then show the dialogue between the user and the steward").
   ONE mechanism for both pages: the page long-polls the cockpit's own event stream (/api/steward/events — the one the
   AI Cockpit uses) from the moment it opens (the cockpit's own soft start: a parked steward with work kept for it
   resumes; a brand-new one is never woken by a mere view); what the steward writes lands as it writes — in the page's
   dialogue and, when the turn was sent from a goal's brainstorm, there too (one log, two views); the steward's state
   (parked · waking · listening · working) stands at the dialogue's head; a turn that changed the record reloads the
   page with the receipt kept; a send from a tab older than the server renews the page with the draft kept. */
(function () {
  'use strict';
  function init(o) {
    var $ = function (s, r) { return (r || document).querySelector(s); };
    var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
    var PID = o.pid || '', DIR = o.dir || '', headers = o.headers, receipt = o.receipt || function () {};
    var STEWARD = o.steward || 'The steward', BOOT_STAMP = o.stamp || '', KEY = o.receiptKey || 'steward_receipt';
    var goalName = o.goalName || function (id) { return id; }, openGoal = o.openGoal || null;
    var live = { seq: 0, polling: false, target: null, goal: null, line: null, epoch: null, skipJohn: '', stopped: false };
    function keep(text, bad, undo) { try { sessionStorage.setItem(KEY, JSON.stringify({ text: text, bad: !!bad, undo: undo || null })); } catch (e) {} }
    function mainList() { return $(o.list || '#exList'); }
    function exLi(who, text, cls, goal) {
      var li = document.createElement('li');
      li.className = 'exrow ' + (who === 'you' ? 'you' : (who === 'st' ? 'st' : 'sysl')) + (cls ? ' ' + cls : '');
      li.innerHTML = '<div class="exw ' + (who === 'you' ? 'you' : 'st') + '"><span class="w"></span><span class="t"></span></div><div class="ext"></div>';
      li.querySelector('.w').textContent = who === 'you' ? 'You' : (who === 'st' ? STEWARD : '');
      if (goal) {
        var c = document.createElement('button'); c.className = 'gchip'; c.title = 'this goal'; c.textContent = 'about ' + goalName(goal);
        li.querySelector('.exw').insertBefore(c, li.querySelector('.t'));
        c.addEventListener('click', function () { if (openGoal) openGoal(goal); });
      }
      li.querySelector('.ext').textContent = text;
      return li;
    }
    function settle(list) { list.scrollTop = list.scrollHeight; var sc = list.closest('.scroll'); if (sc) sc.scrollTop = sc.scrollHeight; }
    function put(list, li) { if (!list) return null; var fade = list.querySelector('.exfade'); if (fade) fade.remove(); list.appendChild(li); settle(list); return li; }
    // one log, two views: a line lands in the list that sent the turn and, when that is a goal's thread, in the
    // page's dialogue as well, with the goal's chip
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
    function showState(s) { var el = $(o.state || '#exState'); if (!el || !s) return; el.textContent = stateText(s); el.setAttribute('data-state', s.busy ? 'busy' : (s.alive ? 'idle' : 'parked')); }
    // a GET on these pages carries the token on the query (the dashboard convention; the server's GET gate does not read
    // the header) — his polls were refused with the header alone and the page asked again three times a second (W2c-3)
    function tokenQ() { var t = ''; try { t = localStorage.getItem('anchor_token') || ''; } catch (e) {} return t ? ('&token=' + encodeURIComponent(t)) : ''; }
    function q() { return '?pid=' + encodeURIComponent(PID) + '&dir=' + encodeURIComponent(DIR) + tokenQ(); }
    var refused = false;
    function refusedOnce() {   // a refused poll: said once, the loop stopped; the page's own login (when it has one) is offered
      if (refused) return; refused = true; live.polling = false;
      var el = $(o.state || '#exState'); if (el) { el.textContent = 'not logged in — the steward’s words cannot reach this page'; el.setAttribute('data-state', 'auth'); }
      live.target = null; live.goal = null;
      appendLine('sys', 'This browser is not logged in to Anchor, so the steward’s words cannot reach this page. Paste the token (the High Seat has the box), then reload.', 'dim');
      if (o.onAuth) o.onAuth();
    }
    function asJson(r) { if (r.status === 401 || r.status === 403) { var e = new Error('auth'); e.auth = true; throw e; } return r.json(); }
    // a turn that ended before this page saw its words (it was mid-turn when the page opened): the log has it
    function catchUp() {
      fetch('/api/steward/history' + q(), { headers: headers() })
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
      return fetch('/api/steward/events' + q() + '&since=0', { headers: headers() })
        .then(asJson)
        .then(function (j) { (j.events || []).forEach(function (ev) { live.seq = Math.max(live.seq, ev.seq || 0); }); if (j.state && j.state.epoch !== undefined) live.epoch = j.state.epoch; showState(j.state); })
        .catch(function (e) { if (e && e.auth) refusedOnce(); });
    }
    function pollLoop() {
      if (live.polling) return; live.polling = true;
      (function step() {
        if (live.stopped) { live.polling = false; return; }   // W2e: a card's dialogue stops when the card closes
        fetch('/api/steward/events' + q() + '&since=' + live.seq, { headers: headers() })
          .then(asJson)
          .then(function (j) {
            if (!j || !j.events) { setTimeout(step, 3000); return; }   // an answer with no stream in it: wait, never hammer
            var ep = j.state && j.state.epoch;
            if (ep !== undefined && live.epoch !== null && ep !== live.epoch) { live.seq = 0; live.epoch = ep; appendLine('sys', '— the steward reconnected —', 'dim'); }
            else if (ep !== undefined) live.epoch = ep;
            showState(j.state);
            (j.events || []).forEach(function (ev) { live.seq = Math.max(live.seq, ev.seq || 0); handleEvent(ev); });
            if (j.stamp && BOOT_STAMP && j.stamp !== BOOT_STAMP && !live.line) {
              keep('The steward changed the record — the page is reloaded.', false, null);
              location.reload(); return;
            }
            if (!live.stopped) setTimeout(step, 250);
          })
          .catch(function (e) { if (e && e.auth) { refusedOnce(); return; } if (!live.stopped) setTimeout(step, 3000); });
      })();
    }
    function send(text, goal, list, btn, box, DK) {
      btn.disabled = true; btn.textContent = 'Thinking…';
      (live.polling ? Promise.resolve() : primeSeq()).then(function () {
        return fetch('/api/steward/say', { method: 'POST', headers: headers(), body: JSON.stringify({ pid: PID, dir: DIR, text: text, goal: goal || undefined }) });
      })
        .then(asJson)
        .then(function (j) {
          btn.disabled = false; btn.textContent = 'Send';
          if (j && j.error === 'build-mismatch') {   // a stale tab: the draft is kept in this browser; the renewed page puts it back
            keep('This page was older than the server — it is renewed; your unsent text is back in the box, send it again.', true, null);
            location.reload(); return;
          }
          if (!j || j.ok === false) {
            var why = (j && (j.say || j.receipt || j.error || j.message)) || 'No answer came back — nothing was done.';
            if (j && j.undo) { keep(why, true, j.undo); location.reload(); return; }   // a verb that landed in part: the refusal and its undo survive the reload
            receipt(why, true); live.target = list; live.goal = goal || null; appendLine('sys', 'Not sent — ' + why, 'dim'); live.target = null; live.goal = null; return;
          }
          try { if (DK) localStorage.removeItem(DK); } catch (e) {}
          if (j.campaign_act && !j.read_only) {   // a Campaign verb: the record changed; the receipt and its undo survive the reload
            keep(j.say, false, j.undo || null);
            location.reload(); return;
          }
          box.value = '';
          live.target = list; live.goal = goal || null; live.line = null; live.skipJohn = text;
          appendLine('you', text);
          if (j.queued) appendLine('sys', 'queued — the steward is mid-turn; yours goes next', 'dim');
          receipt(goal ? 'Said to the steward about this goal — it answers as it writes.' : 'Said — the steward answers above as it writes.');
          if (!refused) pollLoop();
        })
        .catch(function (e) { btn.disabled = false; btn.textContent = 'Send'; if (e && e.auth) { refusedOnce(); receipt('Not sent — this browser is not logged in to Anchor.', true); return; } receipt('That did not go through — nothing was done.', true); });
    }
    // live from the open: the ring's top first (so the log shown below is not replayed), then the stream
    if (PID && mainList()) primeSeq().then(function () { if (!refused) pollLoop(); });
    function stop() { live.stopped = true; }
    return { send: send, appendLine: appendLine, mainList: mainList, stop: stop };
  }
  window.StewardDialogue = { init: init };
})();
