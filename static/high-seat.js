/* ═══════════════════════════════════════════════════════════════════════
   Ecgberht High Seat — wireframes v2.1 Screens 0 + 2 + 3 (TW6).
   Docked overlay over the live Anchor MAIN dashboard (portfolio altitude).

   Renders ONLY the engine view model served by /api/ecgberht/high_seat
   (high-seat-bridge.mjs → engine/high-seat.mjs). The panel invents no
   state: one raised block at most, tiles are one line each (never a master
   data table), capacity is spoken known|unknown (no %-meters, no token
   gauges), and the ⚑ badge on the toolbar button — raise-queue length —
   is the ONLY ambient Ecgberht signal anywhere in Anchor.

   "Bring it up" hops IN-OVERLAY to the project's Decision Packet (Screen 3,
   Option P path passport — same strip the project Seal opens); Esc or the
   breadcrumb returns. Closing the overlay writes nothing (a seen receipt is
   the only ledger delta a close may ever cause). Dialogue is ephemeral:
   talk compiles to closed verbs + receipts, and nothing here persists panel
   truth locally.
   ═══════════════════════════════════════════════════════════════════════ */

function _ecgHsEl(tag, cls, text) {
  var el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text != null) el.textContent = text;
  return el;
}

function _ecgHsTok() {
  try {
    var t = (typeof _anchorToken === 'function') ? _anchorToken() : '';
    return t ? '&token=' + encodeURIComponent(t) : '';
  } catch (e) { return ''; }
}

function _ecgHsGet(path, done, fail) {
  fetch(path + _ecgHsTok())
    .then(function (r) { return r.json(); })
    .then(done)
    .catch(fail || function () {});
}

function _ecgHsPost(body, done) {
  fetch('/api/ecgberht/high_seat_act' + (_ecgHsTok() ? '?' + _ecgHsTok().slice(1) : ''), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body)
  }).then(function (r) { return r.json(); }).then(done).catch(function () {});
}

/* ── S0-E2: ⚑ badge = raise queue length (the only ambient signal) ── */
function ecgHighSeatBadge(done) {
  var badge = document.getElementById('ecgHighSeatBadge');
  if (!badge) { if (done) done(true); return; }
  _ecgHsGet('/api/ecgberht/high_seat_badge?', function (out) {
    var ok = !!(out && out.ok);
    if (!ok) {
      // The server distinguishes "no projects" (ok, count 0) from
      // "registry unreadable" (queue_length null). Never render an unknown
      // queue as 0 — that reads as "nothing needs you", which is a lie.
      badge.textContent = '';
      badge.className = 'ecg-hs-badge';
      if (done) done(false);
      return;
    }
    var n = out.queue_length || 0;
    badge.textContent = '⚑ ' + n;
    badge.className = n > 0 ? 'ecg-hs-badge on' : 'ecg-hs-badge';
    if (done) done(true);
  });
}

function closeEcgberhtHighSeat() {
  var dock = document.getElementById('ecgHighSeatDock');
  if (dock) dock.remove();
  // Close law: the ledger gains nothing here (at most a seen receipt when
  // one is explicitly requested); panel state simply evaporates.
}

function _ecgHsActions(defs) {
  var row = _ecgHsEl('div', 'ecg-hs-actions');
  defs.forEach(function (d) {
    var b = _ecgHsEl('button', d.pri ? 'pri' : null, d.label);
    b.onclick = d.onclick;
    row.appendChild(b);
  });
  return row;
}

function _ecgHsReply(host, text) {
  var r = _ecgHsEl('div', 'ecg-hs-reply', text);
  host.appendChild(r);
  return r;
}

/* ── Screen 3: the Decision Packet, rendered in the SAME dock ── */
function _ecgHsRenderPacket(body, pid, payload) {
  body.innerHTML = '';
  var crumb = _ecgHsEl('div', 'ecg-hs-crumb', '← back to the High Seat (Esc)');
  crumb.onclick = function () { _ecgHsLoadHighSeat(body); };
  body.appendChild(crumb);

  var pv = payload.packet_view;
  var wrap = _ecgHsEl('div', 'ecg-hs-packet');
  body.appendChild(wrap);

  (pv.cards || []).forEach(function (card) {
    var el = _ecgHsEl('div', 'ecg-hs-pcard' + (card.card === 'remember_the_goal' ? ' goal' : ''));
    if (card.card === 'remember_the_goal') {
      el.appendChild(_ecgHsEl('h3', null, 'Remember the goal · North Star (Face)'));
      el.appendChild(_ecgHsEl('div', card.unknown ? 'unknown' : null, card.goal));
      if (card.unchanged_since) {
        el.appendChild(_ecgHsEl('div', 'prov', 'Face · unchanged since ' + card.unchanged_since));
      }
    } else if (card.card === 'where_we_are') {
      el.appendChild(_ecgHsEl('h3', null, 'Where we are'));
      el.appendChild(_ecgHsEl('div', card.unknown ? 'unknown' : null, card.line));
      el.appendChild(_ecgHsEl('div', 'prov', 'Campaign Roadmap · typed ledger'));
    } else if (card.card === 'since_you_last_looked') {
      el.appendChild(_ecgHsEl('h3', null, 'Since you last looked'));
      el.appendChild(_ecgHsEl('div', card.unknown ? 'unknown' : null,
        card.unknown ? String(card.delta) : JSON.stringify(card.delta)));
    } else if (card.card === 'the_thing_itself') {
      el.appendChild(_ecgHsEl('h3', null, 'The thing itself · rendered, not linked-and-forgotten'));
      if (card.unknown) {
        el.appendChild(_ecgHsEl('div', 'unknown', card.voice));
      } else {
        var art = _ecgHsEl('div', 'ecg-hs-art');
        var artUrl = '/api/ecgberht/artifact?project_id=' + encodeURIComponent(pid) +
          '&rel=' + encodeURIComponent(card.ref) + _ecgHsTok();
        if (card.inline && card.inline.mode === 'iframe') {
          // Artifact display MVP: HTML mockups render best-effort inline.
          var frame = document.createElement('iframe');
          frame.src = artUrl;
          frame.setAttribute('sandbox', '');
          art.appendChild(frame);
        }
        art.appendChild(_ecgHsEl('div', 'prov', card.title || card.ref));
        el.appendChild(art);
        el.appendChild(_ecgHsActions([
          { label: 'Open full', pri: true, onclick: function () { window.open(artUrl, '_blank'); } },
          { label: 'Walk me through', onclick: function () {
              _ecgHsReply(el, 'Walk-through: open-in-viewer + steward narration lands in a later PE wave — for now, "Open full" shows the artifact itself.');
            } }
        ]));
      }
    } else if (card.card === 'what_i_need_from_you') {
      el.appendChild(_ecgHsEl('h3', null, 'What I need from you'));
      el.appendChild(_ecgHsEl('div', null, card.question));
      var rec = _ecgHsEl('div', 'prov');
      rec.textContent = 'My recommendation: ' + (card.recommendation ? card.recommendation.text : '');
      el.appendChild(rec);
      if (card.recommendation && card.recommendation.reasons && card.recommendation.reasons.length) {
        var ul = _ecgHsEl('ul', 'ecg-hs-reasons open');
        card.recommendation.reasons.forEach(function (r) { ul.appendChild(_ecgHsEl('li', null, r)); });
        el.appendChild(ul);
      }
      var decide = function (decision, edits) {
        _ecgHsPost({
          kind: 'decide', project_id: pid, step_id: card.step_id,
          decision: decision, who: 'john', why: edits || null
        }, function (out) {
          if (out && out.ok && out.moved) {
            _ecgHsReply(el, 'Receipt landed — the Roadmap moved (' + card.step_id + ' → done). ' +
              (out.persisted ? 'Persisted through the single writer.' : ''));
            ecgHighSeatBadge();
          } else if (out && out.ok) {
            _ecgHsReply(el, 'Held — nothing written until you decide.');
          } else {
            _ecgHsReply(el, 'Refused: ' + ((out && (out.error || out.message)) || 'unknown'));
          }
        });
      };
      el.appendChild(_ecgHsActions([
        { label: 'Lock it', pri: true, onclick: function () { decide('lock_it'); } },
        { label: 'Lock with edits…', onclick: function () {
            var edits = prompt('Your edits (land in the decision receipt):');
            if (edits != null && edits !== '') decide('lock_with_edits', edits);
          } },
        { label: 'Not yet — talk it through', onclick: function () { decide('not_yet'); } }
      ]));
    }
    wrap.appendChild(el);
  });

  wrap.appendChild(_ecgHsEl('div', 'ecg-hs-pcard prov', pv.footer_stamp));
}

function ecgHsBringUp(body, pid) {
  _ecgHsGet('/api/ecgberht/bring_up?project_id=' + encodeURIComponent(pid), function (out) {
    if (!out || !out.ok) {
      _ecgHsReply(body, 'Bring it up failed: ' + ((out && (out.error || out.message)) || 'no response'));
      return;
    }
    // S0-E5: same overlay, no second window — the altitude hop is a non-event.
    _ecgHsRenderPacket(body, pid, out);
  });
}

/* ── Screen 2: the High Seat body ── */
function _ecgHsRenderHighSeat(body, vm) {
  body.innerHTML = '';

  // S2-E2 — the single raise block (or the honest quiet voice)
  var rb = vm.raise_block;
  if (rb && rb.present) {
    var raise = _ecgHsEl('div', 'ecg-hs-raise');
    raise.appendChild(_ecgHsEl('h3', null, rb.heading));
    var line = (rb.project_id || '') + ' — ' + rb.summary +
      (rb.time_estimate ? ' · ' + rb.time_estimate : '');
    raise.appendChild(_ecgHsEl('div', null, line));
    raise.appendChild(_ecgHsActions([
      { label: 'Bring it up', pri: true, onclick: function () { ecgHsBringUp(body, rb.project_id); } },
      { label: 'Later today', onclick: function () {
          _ecgHsReply(raise, 'Set aside for this sitting — nothing written; it stays in the queue.');
        } },
      { label: 'Tomorrow', onclick: function () {
          _ecgHsReply(raise, 'Set aside for this sitting — nothing written; it stays in the queue.');
        } }
    ]));
    raise.appendChild(_ecgHsEl('div', 'note', rb.queue_note));
    body.appendChild(raise);
  } else {
    body.appendChild(_ecgHsEl('div', 'ecg-hs-quiet', rb ? rb.voice : ''));
  }

  // S2-E3 — tiles: seal + goal-phrase + one state pill each; never a table
  var tiles = _ecgHsEl('div', 'ecg-hs-tiles');
  (vm.tiles.tiles || []).forEach(function (t) {
    var tile = _ecgHsEl('div', 'ecg-hs-tile' + (t.dimmed ? ' dim' : ''));
    var nm = _ecgHsEl('div', 'nm');
    var ico = document.createElement('img');
    ico.src = '/vendor/brand/ecgberht-project-seal.jpg';
    ico.alt = '';
    ico.onerror = function () { this.style.display = 'none'; };
    nm.appendChild(ico);
    nm.appendChild(_ecgHsEl('span', null, t.name));
    tile.appendChild(nm);
    tile.appendChild(_ecgHsEl('div', 'goal', t.goal_phrase));
    tile.appendChild(_ecgHsEl('div', 'pill' + (t.state_kind === 'raised' ? ' raised' : ''), t.state_pill));
    tiles.appendChild(tile);
  });
  body.appendChild(tiles);

  // S2-E4 — capacity & focus: spoken recommendation + reasons + override
  var bal = vm.balancing;
  var card = _ecgHsEl('div', 'ecg-hs-balance');
  card.appendChild(_ecgHsEl('div', 'who', 'Ecgberht · capacity & focus'));
  card.appendChild(_ecgHsEl('div', null, bal.steward_voice));
  var reasons = _ecgHsEl('ul', 'ecg-hs-reasons');
  (bal.recommendation.reasons || []).forEach(function (r) {
    reasons.appendChild(_ecgHsEl('li', null, r));
  });
  card.appendChild(_ecgHsActions([
    { label: 'Do that', pri: true, onclick: function () {
        _ecgHsReply(card, 'Held to the recommended order — no override needed, nothing written.');
      } },
    { label: 'Reorder…', onclick: function () {
        var to = prompt('Your order (e.g. "trio, foundry") — the override lands as a receipt:');
        if (to == null || to === '') return;
        _ecgHsPost({
          kind: 'override', who: 'john',
          why: 'High Seat balancing reorder',
          from: (bal.recommendation.order || []).join(','), to: to
        }, function (out) {
          _ecgHsReply(card, out && out.ok
            ? 'Override receipt landed (who/when/why/from→to).'
            : 'Refused: ' + ((out && (out.error || out.message)) || 'unknown'));
        });
      } },
    { label: 'Why? show reasoning', onclick: function () {
        reasons.className = reasons.className.indexOf('open') >= 0
          ? 'ecg-hs-reasons' : 'ecg-hs-reasons open';
      } }
  ]));
  card.appendChild(reasons);
  card.appendChild(_ecgHsEl('div', 'mech', bal.mechanics_stamp));
  body.appendChild(card);

  // TW7 S4-E2 — capacity-unknown hard-stop chamber: a SPOKEN refusal with
  // exactly three honest options. No %-meter, no token gauge, and no code
  // path that admits a FULL run silently while capacity is unknown.
  var cuc = vm.capacity_unknown_chamber;
  if (cuc && cuc.hard_stop) {
    var stop = _ecgHsEl('div', 'ecg-hs-balance ecg-hs-capstop');
    stop.appendChild(_ecgHsEl('div', 'who', 'Ecgberht · capacity unknown — hard stop'));
    stop.appendChild(_ecgHsEl('div', null, cuc.voice +
      (cuc.projects && cuc.projects.length ? ' (' + cuc.projects.join(', ') + ')' : '')));
    var choose = function (choice) {
      var fields = { kind: 'capacity_choice', choice: choice, who: 'john' };
      if (choice === 'override') {
        var why = prompt('Override the hard stop — why? (lands as a receipt, who/when/why/from→to):');
        if (why == null || why === '') return;
        fields.why = why;
      }
      _ecgHsPost(fields, function (out) {
        if (out && out.ok) {
          _ecgHsReply(stop, out.voice ||
            (out.admitted === 'FULL'
              ? 'FULL admitted via override — the receipt landed (who/when/why/from→to).'
              : 'Done.'));
        } else {
          _ecgHsReply(stop, 'Refused: ' + ((out && (out.error || out.message)) || 'unknown') +
            ' — no silent FULL, ever.');
        }
      });
    };
    stop.appendChild(_ecgHsActions((cuc.options || []).map(function (o) {
      return { label: o.label, pri: o.choice === 'lite_now',
               onclick: function () { choose(o.choice); } };
    })));
    stop.appendChild(_ecgHsEl('div', 'mech',
      'spoken, never a meter · unknown capacity cannot silent-FULL · override = receipt'));
    body.appendChild(stop);
  }

  // S2-E5 — saybox
  var say = _ecgHsEl('div', 'ecg-hs-say');
  var input = document.createElement('input');
  input.placeholder = vm.saybox.placeholder;
  var speakBtn = _ecgHsEl('button', null, 'Speak');
  var speak = function () {
    var text = input.value.trim();
    if (!text) return;
    input.value = '';
    _ecgHsPost({ kind: 'speak', text: text }, function (out) {
      if (!out || !out.ok) return;
      var c = out.compiled;
      if (c && c.compiled && c.act === 'bring_it_up' && rb && rb.present) {
        ecgHsBringUp(body, rb.project_id);
      } else if (c && c.compiled) {
        _ecgHsReply(card, 'Compiled to the closed act "' + c.act + '" — dialogue stays ephemeral.');
      } else {
        _ecgHsReply(card, (c && c.proposal) ? c.proposal
          : 'That does not compile to a closed act — refuse-with-proposal; nothing was written.');
      }
    });
  };
  speakBtn.onclick = speak;
  input.onkeypress = function (e) { if (e.key === 'Enter') speak(); };
  say.appendChild(input);
  say.appendChild(speakBtn);
  body.appendChild(say);
}

function _ecgHsLoadHighSeat(body) {
  _ecgHsGet('/api/ecgberht/high_seat?', function (out) {
    if (!out || !out.ok) {
      body.innerHTML = '';
      body.appendChild(_ecgHsEl('div', 'ecg-hs-quiet',
        'High Seat unavailable: ' + ((out && (out.error || out.message)) || 'no response')));
      return;
    }
    _ecgHsRenderHighSeat(body, out.high_seat);
  });
}

function openEcgberhtHighSeat() {
  var host = document.getElementById('ecgHighSeatHost');
  if (!host) return;
  var existing = document.getElementById('ecgHighSeatDock');
  if (existing) { existing.remove(); return; }

  _ecgHsGet('/api/ecgberht/high_seat?', function (out) {
    if (document.getElementById('ecgHighSeatDock')) return;
    var dock = _ecgHsEl('div', 'ecg-hs-dock');
    dock.id = 'ecgHighSeatDock';

    // S2-E1 — titlebar
    var bar = _ecgHsEl('div', 'ecg-hs-bar');
    var ico = document.createElement('img');
    ico.className = 'ecg-hs-ico';
    ico.src = '/vendor/brand/ecgberht-portfolio-high-seat.jpg';
    ico.alt = '';
    ico.onerror = function () { this.style.display = 'none'; };
    bar.appendChild(ico);
    var ti = _ecgHsEl('span', 'ti', 'Ecgberht ');
    var vm = out && out.ok ? out.high_seat : null;
    ti.appendChild(_ecgHsEl('small', null,
      '· the High Seat — every campaign, one steward above them'));
    bar.appendChild(ti);
    if (vm) {
      bar.appendChild(_ecgHsEl('span', 'seatpill', vm.titlebar.seat_switcher.pill));
      bar.appendChild(_ecgHsEl('span', 'stamp', vm.titlebar.stamp));
    } else {
      bar.appendChild(_ecgHsEl('span', 'stamp', ''));
    }
    var fsBtn = _ecgHsEl('button', null, '⛶');
    fsBtn.title = 'Full screen';
    fsBtn.onclick = function () {
      dock.className = dock.className.indexOf('full') >= 0 ? 'ecg-hs-dock' : 'ecg-hs-dock full';
    };
    bar.appendChild(fsBtn);
    var closeBtn = _ecgHsEl('button', null, '×');
    closeBtn.title = 'Close (ledger unchanged — a seen receipt is the most a close may write)';
    closeBtn.onclick = closeEcgberhtHighSeat;
    bar.appendChild(closeBtn);
    dock.appendChild(bar);

    var body = _ecgHsEl('div', 'ecg-hs-body');
    dock.appendChild(body);

    var foot = _ecgHsEl('div', 'ecg-hs-foot',
      'one raised item at a time · tiles are one line each · rank/force-choice/capacity laws run underneath, not on stage · talk → closed verbs + receipts · dialogue ephemeral');
    dock.appendChild(foot);

    host.appendChild(dock);
    if (vm) {
      _ecgHsRenderHighSeat(body, vm);
    } else {
      body.appendChild(_ecgHsEl('div', 'ecg-hs-quiet',
        'High Seat unavailable: ' + ((out && (out.error || out.message)) || 'no response')));
    }

    var esc = function (e) {
      if (e.key === 'Escape') {
        var packetOpen = body.querySelector('.ecg-hs-packet');
        if (packetOpen) { _ecgHsLoadHighSeat(body); } // breadcrumb: packet → High Seat
        else { closeEcgberhtHighSeat(); document.removeEventListener('keydown', esc); }
      }
    };
    document.addEventListener('keydown', esc);
  });
}

/* Ambient init: the badge is the only Ecgberht signal outside the overlay. */
(function () {
  // The badge poll reaches an endpoint that SPAWNS A NODE SUBPROCESS on the
  // server, so a plain 90s setInterval means every open tab — including ones
  // sitting behind other windows for days — spawns a process forever, and
  // keeps spawning at full rate when the bridge is failing. That is the same
  // shape as the zombie-hunter restart storm, just slower. So: skip the poll
  // while the tab is hidden (refresh once on becoming visible), and back off
  // geometrically on consecutive failures, resetting on the first success.
  var MIN_MS = 90000, MAX_MS = 15 * 60 * 1000;
  var fails = 0, timer = null;

  var delay = function () {
    var d = MIN_MS * Math.pow(2, Math.min(fails, 4));
    return Math.min(d, MAX_MS);
  };

  var schedule = function () {
    if (timer) { clearTimeout(timer); timer = null; }
    timer = setTimeout(tick, delay());
  };

  var tick = function () {
    if (document.hidden) { schedule(); return; }   // nobody is looking
    ecgHighSeatBadge(function (ok) {
      fails = ok ? 0 : fails + 1;
      schedule();
    });
  };

  var boot = function () {
    tick();
    document.addEventListener('visibilitychange', function () {
      if (!document.hidden) { fails = 0; tick(); }  // refresh on return
    });
    window.addEventListener('pagehide', function () {
      if (timer) { clearTimeout(timer); timer = null; }
    });
  };
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
