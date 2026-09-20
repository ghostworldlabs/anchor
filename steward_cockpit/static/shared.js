/* steward-proto shared client. Safe rendering: model text goes through
   textContent-based builders only - no innerHTML anywhere.
   All API calls carry the effort's dir (?dir=<rel>) so one server hosts
   several steward efforts at once. */
"use strict";

const Proto = (() => {
  const PARAMS = new URLSearchParams(location.search);
  const DIR = PARAMS.get("dir") || "";
  const GENERAL = PARAMS.get("general") === "1";
  const TERM = PARAMS.get("term") || "";
  const EMBED = PARAMS.get("embed") === "1";
  let seq = 0, stamp = "", busySince = null, currentBlock = null,
      opts = {}, map = null, lastState = null, latestStatusId = "";

  const $ = (s) => document.querySelector(s);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const api = (path) => path + (path.includes("?") ? "&" : "?") +
    "dir=" + encodeURIComponent(DIR) + (GENERAL ? "&general=1" : "") +
    (TERM ? "&term=" + encodeURIComponent(TERM) : "");
  const post = (path, body) => fetch(path, { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(Object.assign(
      { dir: DIR, general: GENERAL, term: TERM || undefined }, body)) });
  // reports-links W3: authed JSON POST to an ANCHOR route (not a steward verb —
  // the page shim passes /api/rnd/ through unrewritten). Same token path the
  // tidy-idy caller uses: Bearer + X-Anchor-Token from the page token.
  function _postJson(url, payload) {
    const headers = { "Content-Type": "application/json" };
    let tok = window.STEWARD_TOKEN || "";
    try { tok = tok || localStorage.getItem("anchor_token") || ""; } catch (e) {}
    if (tok) {
      headers["X-Anchor-Token"] = tok;
      headers["Authorization"] = "Bearer " + tok;
    }
    return fetch(url, { method: "POST", headers: headers,
                        body: JSON.stringify(payload) });
  }
  function oneLine(value, limit=110) {
    const full = String(value || "").replace(/\s+/g, " ").trim();
    if (!full) return "";
    const match = full.match(/^(.{20,}?)(?<!\d)[.!?](?:\s|$)/);
    const sentence = match ? match[0].trim() : full;
    if (sentence.length <= limit) return sentence;
    return sentence.slice(0, limit - 1).replace(/\s+\S*$/, "") + "…";
  }
  function hasWaitingOn(value) {
    if (Array.isArray(value)) return value.length > 0;
    if (value && typeof value === "object") return Object.keys(value).length > 0;
    return !!(value && String(value).trim());
  }
  function stepDone(st) {
    if (!st) return false;
    if (st.refinement) return st.refinement.phase === "done";
    return st.status === "done";
  }
  function stepNeedsAttention(st) {
    if (!st) return false;
    if (st.status === "waiting" || st.status === "blocked") return true;
    if (hasWaitingOn(st.waiting_on)) return true;
    const r = st.refinement;
    if (r && (r.phase === "awaiting_review" || r.phase === "blocked")) return true;
    return ((r && r.producer_handoffs) || []).some(h => h && h.status === "pending_steward_review");
  }
  function planMarkInfo(st) {
    if (stepDone(st)) return {glyph: "✓", cls: "done", row: "done"};
    if (stepNeedsAttention(st)) return {glyph: "⚑", cls: "flag", row: "waiting"};
    return {glyph: "▷", cls: "todo", row: st.status === "active" ? "active" : "planned"};
  }
  function currentQuestion() {
    const questions = (lastState && lastState.pending_questions) || [];
    return questions[0] || lastState?.question_context ||
      (lastState?.open_question ? {question: lastState.open_question} : null);
  }
  function fillQuestionPanel(host, q) {
    host.textContent = "";
    const pending = () => (lastState && lastState.pending_questions) || [];
    const gone = (btn) => { btn.disabled = true; host.appendChild(el("p", "", "This question changed or was resolved. Open the current question.")); };
    // four short lines under ONE ~60-word budget: the stake · the recommendation (the first button) and why · the alternatives · the question
    let budget = 360;
    const take = (text, cap) => { const t = oneLine(text, Math.max(24, Math.min(cap, budget))); budget -= t.length; return t; };
    if (q.stake) host.appendChild(el("p", "action-stake", take(q.stake, 160)));
    if (!q.recommendation) host.appendChild(el("p", "action-rec dim", "no recommendation given"));
    if (q.recommendation) {
      const row = el("p", "action-rec");
      const accept = el("button", "action-accept", "Accept recommendation");
      accept.onclick = async (ev) => {
        ev.stopPropagation();
        if (q.id && !pending().some(item => item.id === q.id)) return gone(accept);
        accept.disabled = true;
        const tile = host.closest("[data-openq],[data-status-action]");
        const result = await sendSay("Accept recommendation: " + q.recommendation, q.id || null);
        if (result && result.ok) { if (tile) tile.classList.remove("open"); }
        else accept.disabled = false;
      };
      row.appendChild(accept);
      row.appendChild(el("span", "action-rectext", " " + take(q.recommendation, 160) + (q.why ? " \u2014 " + take(q.why, 120) : "")));
      host.appendChild(row);
    }
    if ((q.alternatives || []).length && budget > 24)
      host.appendChild(el("p", "action-alts", "Or: " + q.alternatives.slice(0, 3).map(a => take(a, 90)).join(" \u00b7 ")));
    if (q.id) {
      const answer = el("button", "", "Answer this question");
      answer.onclick = (ev) => {
        ev.stopPropagation();
        if (!pending().some(item => item.id === q.id)) return gone(answer);
        _answerQuestionId = q.id;
        const ta = $("[data-say]");
        if (ta) { ta.placeholder = "Answer: " + q.question; ta.focus(); }
      };
      host.appendChild(answer);
    }
    // everything else - the literal context, its source and scope - behind one disclosure
    const more = el("details", "action-context");
    more.appendChild(el("summary", "", "Full context"));
    more.appendChild(el("p", "question-source", q.context || "No additional context was saved."));
    if (q.truncated) more.appendChild(el("p", "sdmeta", "This is an excerpt. The original exchange contains the full context."));
    if (q.source_ref) more.appendChild(el("p", "sdmeta", "Source: " + q.source_ref));
    const scope = q.authorization_scope || {};
    const scopeBits = [scope.step_id, scope.presentation_id, scope.request_id, scope.product_id].filter(Boolean);
    if (scopeBits.length) more.appendChild(el("p", "sdmeta", "Applies to " + scopeBits.join(" \u00b7 ")));
    if (q.authorization) more.appendChild(el("p", "sdmeta", "An answer would " + q.authorization));
    if (q.what_changed) more.appendChild(el("p", "sdmeta", "Replaces: " + oneLine(q.what_changed, 120)));
    host.appendChild(more);
    if (scope.source_turn_id) {
      const source = el("button", "", "Original exchange");
      source.onclick = async (ev) => {
        ev.stopPropagation();
        if (host.querySelector("details.exchange")) return;
        source.disabled = true;
        try {
          const response = await fetch(api("/api/history") + "&turn_id=" + encodeURIComponent(scope.source_turn_id));
          const result = await response.json();
          if (!response.ok) throw Error(result.error || "Original exchange unavailable");
          const history = el("details", "exchange");
          history.open = true;
          history.appendChild(el("summary", "", "Original exchange"));
          (result.turns || []).forEach(turn => {
            history.appendChild(el("h3", "", turn.role === "john" ? "You" : "Steward"));
            history.appendChild(el("div", "question-source", turn.text));
          });
          host.appendChild(history);
        } catch (error) {
          host.appendChild(el("p", "sdmeta", error.message));
          source.disabled = false;
        }
      };
      host.appendChild(source);
    }
    // what John already decided, one click away (never re-asked)
    const decided = (lastState && lastState.decision_history) || [];
    if (decided.length) {
      const d = el("details", "action-history");
      d.appendChild(el("summary", "", "Earlier decisions \u00b7 " + decided.length));
      decided.slice().reverse().forEach(h => d.appendChild(el("p", "sdmeta", oneLine(h.question, 90) + " \u2192 " + oneLine(h.answer, 60))));
      host.appendChild(d);
    }
    pending().filter(item => item.id !== q.id).forEach(item => {
      const b = el("button", "question-other", item.question);
      b.onclick = (ev) => { ev.stopPropagation(); paintActionNeeded(host.closest("[data-openq],[data-status-action]"), item.id); };
      host.appendChild(b);
    });
  }
  function paintActionNeeded(host, questionId=null) {
    if (!host) return;
    const questions = (lastState && lastState.pending_questions) || [];
    const q = questions.find(x => x.id === questionId) || currentQuestion();
    if (!q || !q.question) {
      host.textContent = "";
      host.classList.remove("show", "open");
      delete host.dataset.questionId;
      return;
    }
    const qid = q.id || q.question;
    if (!questionId && host.dataset.questionId === qid && host.classList.contains("show")) return;
    const wasOpen = host.classList.contains("open") || !!questionId;
    host.textContent = "";
    host.classList.remove("show", "open");
    host.dataset.questionId = qid;
    host.classList.add("show");
    if (wasOpen) host.classList.add("open");
    host.setAttribute("role", "button");
    host.tabIndex = 0;
    host.title = "Show the saved decision context";
    const head = el("div", "action-head");
    head.appendChild(el("strong", "", "Action needed"));
    head.appendChild(el("span", "action-q", q.question));
    host.appendChild(head);
    const close = el("button", "action-close", "×");
    close.setAttribute("aria-label", "Close decision details");
    close.title = "Close and type your own answer";
    close.onclick = (ev) => {
      ev.stopPropagation();
      host.classList.remove("open");
      if (q.id) _answerQuestionId = q.id;
      const ta = $("[data-say]");
      if (ta) { ta.placeholder = "Answer: " + q.question; ta.focus(); }
    };
    host.appendChild(close);
    const more = el("div", "action-more");
    more.dataset.questionDialog = "1";
    more.setAttribute("aria-label", "Question and context");
    fillQuestionPanel(more, q);
    host.appendChild(more);
    const toggle = (ev) => {
      if (ev.target.closest(".action-more button, .action-more details, .action-more a, .action-close")) return;
      host.classList.toggle("open");
    };
    host.onclick = toggle;
    host.onkeydown = ev => {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); host.classList.toggle("open"); }
    };
  }

  /* ---------- kickoff (Gate 5 canary, 2026-09-01) ----------
     The confirmed kickoff is the goal's AUTHORITATIVE form (confirmed intent has
     display precedence; the tag-derived map is fallback only), so it paints FIRST
     inside the Goal bar. The prose comes from the engine's projection (rendered
     from the hashed record — never composed here); an open draft paints as one
     plain "not applied" line; anything else paints nothing. XHR on purpose: the
     client shim rewrites fetch('/api/…') to /api/steward/, and this route is
     Anchor's own GET /api/ecgberht/kickoff_show. Read-only; never throws. */
  // the one-line status of record shown in the top bar (2026-09-03); once a
  // status has painted it, map repaints and the kickoff paint leave it alone
  let _statusLine = "";
  function paintKickoff(briefEl) {
    const box = $("[data-kickoff]");
    if (!box) return;
    const pid = PARAMS.get("pid") || "";
    if (!pid || !DIR) { box.textContent = ""; return; }
    let tok = "";
    try { tok = localStorage.getItem("anchor_token") || ""; } catch (e) { tok = ""; }
    const url = "/api/ecgberht/kickoff_show?pid=" + encodeURIComponent(pid) +
      "&effort=" + encodeURIComponent(DIR) + (tok ? "&token=" + encodeURIComponent(tok) : "");
    const x = new XMLHttpRequest();
    x.open("GET", url, true);
    x.onreadystatechange = () => {
      if (x.readyState !== 4) return;
      let j = null;
      try { j = JSON.parse(x.responseText || "null"); } catch (e) { j = null; }
      box.className = "gkick";
      box.textContent = "";
      if (!j) return;
      // (2026-09-02, John: "the goal section at top is really, really big") — the bar
      // stays CLOSED; the confirmed outcome becomes the one-line brief, and the full
      // bundle is one click away, compact. Nothing auto-opens.
      if (j.ok && j.state === "confirmed" && typeof j.rendered === "string" && j.rendered.trim()) {
        box.classList.add("confirmed");
        renderRich(box, j.rendered);
        // the brief line shows the confirmed outcome — the goal in the steward's own words
        if (briefEl) {
          const m = j.rendered.match(/^Outcome:\s*(.+)$/m);
          if (m && m[1] && !_statusLine) briefEl.textContent = m[1].trim();
        }
      } else if (j.state === "open" && j.open_draft && j.open_draft.applied === false) {
        box.classList.add("draft");
        if (briefEl && j.open_draft.goal && !_statusLine) briefEl.textContent = "draft, not applied — " + j.open_draft.goal;
        box.textContent = "Kickoff draft v" + (j.open_draft.version || "?") +
          " — not applied: " + (j.open_draft.goal || "(no goal in the draft)");
      }
    };
    try { x.send(); } catch (e) { /* offline: paint nothing */ }
  }

  /* ---------- markdown (ONE renderer for the whole package) ----------
     md.js (mdRender) is THE renderer now — the elegance audit's cut of the
     duplicate renderRich/buildTable/renderInline trio. Pages load md.js
     before this file. */
  const renderRich = (container, text) => mdRender(container, text);

  /* ---------- transcript (and, in V1b, the status pane) ---------- */
  function scrollEl() { return $(".scroll"); }
  function paneEl() { return $("[data-statuspane] .pscroll"); }
  function atBottom(s) {
    return s.scrollHeight - s.scrollTop - s.clientHeight < 120;
  }
  function pin(s, force) {
    if (s && (force || atBottom(s))) s.scrollTop = s.scrollHeight;
  }
  function targetFor(ev) {
    if (opts.statusPane && ev && ev.tick && paneEl()) return paneEl();
    return scrollEl();
  }

  function addBlock(kind, who, text, extraClass, ev) {
    const s = targetFor(ev);
    const stick = atBottom(s);
    if (kind === "steward" && s === paneEl() && s) {
      // status fold: only the newest table stays expanded (click unfolds)
      s.querySelectorAll(".blk.steward:not(.folded)").forEach(old => {
        old.classList.add("folded");
        old.onclick = () => old.classList.toggle("folded");
      });
    }
    const b = el("div", "blk " + kind + (extraClass ? " " + extraClass : ""));
    if (who) b.appendChild(el("div", "who", who));
    const body = el("div", "body");
    if (kind === "steward") renderRich(body, text); else body.textContent = text;
    b.appendChild(body);
    s.appendChild(b);
    pin(s, stick);
    return b;
  }
  function addLine(cls, text, ev) {
    const s = targetFor(ev);
    const stick = atBottom(s);
    s.appendChild(el("div", "blk " + cls, text));
    pin(s, stick);
  }
  function closeCurrent() {
    if (currentBlock) {
      const s = currentBlock.parentElement;
      const stick = s && atBottom(s);
      const body = currentBlock.querySelector(".body");
      renderRich(body, currentBlock._raw || body.textContent);
      currentBlock = null;
      if (stick) pin(s, true);
    }
  }

  /* ---------- the deterministic 10-minute status (engine-composed) ----------
     Two parts: NOW (what is running — the steward's turn AND commissioned/
     background runs) over PLAN (step n/m · waiting-on-you · next). Rendered
     into the RIGHT STATUS PANE only — never the conversation. The same shape
     is persisted server-side to .ecgberht/status-summary.json for the
     main-dashboard tile. */
  function renderStatus(stat) {
    const s = paneEl();
    if (!s || !stat) return;
    const statusId = String(stat.status_id || "");
    // The fresh status painted on open must not be replaced by an older
    // status event replayed from the engine buffer.
    if (statusId && latestStatusId && statusId <= latestStatusId) return;
    if (statusId) latestStatusId = statusId;
    const stick = atBottom(s);
    // only the newest status stays expanded (same fold rule as tick turns)
    s.querySelectorAll(".blk.steward:not(.folded)").forEach(old => {
      old.classList.add("folded");
      old.onclick = () => old.classList.toggle("folded");
    });
    const b = el("div", "blk steward status");
    const hhmm = (stat.at || "").slice(-5);
    const who = el("div", "who", "⏱ " + hhmm + " · STATUS");
    who.appendChild(el("span", "live-activity", ""));
    who.lastChild.dataset.liveActivity = "1";
    if (stat.stale) who.appendChild(el("span", "stale",
      " · last update on record — nothing has run since"));
    b.appendChild(who);
    const body = el("div", "body");
    const p = stat.plan || {};
    // Locked 10-minute categories stay visible. Elegance filters the wording
    // of each value, not which rows exist. Earlier updates hold history.
    const goal = (_lastMap && (_lastMap.goal_brief || _lastMap.goal)) || "";
    const seats = (stat.swarm || []).map(x => (x.label || "seat") + " · " + (x.state || "?"));
    const sl = stat.slice || null;
    const run = stat.running || null;
    const sliceLine = sl ? (sl.name + (sl.summary ? " — " + sl.summary : "")) : "";
    const doingLine = (run && run.label) || (stat.now || [])[0] || "";
    const bullets = (stat.next_bullets && stat.next_bullets.length) ? stat.next_bullets
      : (p.next ? [p.next] : []);
    const engineFacts = Array.isArray(stat.compact && stat.compact.facts) ? stat.compact.facts : [];
    const factValue = (label, fallback) => {
      const hit = engineFacts.find(f => f && f.label === label);
      if (hit && hit.value) return hit.value;
      return oneLine(fallback);
    };
    const todo = bullets.length ? el("ul", "stodo") : null;
    if (todo) bullets.slice(0, 3).forEach(t => todo.appendChild(el("li", "", oneLine(t, 90))));
    const rows = [
      ["Summary", factValue("Summary", sliceLine || oneLine(goal) || "—")],
      ["Effort", factValue("Effort", stat.effort || "—")],
      ["Doing", factValue("Doing", doingLine || (stat.stale ? "Idle" : "—"))],
      ["Status", factValue("Status", (p.steps_done || 0) + "/" + (p.steps_total || 0) +
        " done · " + (p.attention || "quiet"))],
      ["Tests", factValue("Tests", stat.tests || "—")],
      ["Blocker", factValue("Blocker", p.waiting_on_you ? "waiting on you: " + p.waiting_on_you
        : (stat.halt && stat.halt.reason) ? "blocked: " + stat.halt.reason : "none")],
      ["Procs", factValue("Procs", seats.length ? seats.join(" · ")
        : ((run && run.kind === "skill") ? run.skill + " (commissioned)" : "none"))],
      ["Journal", factValue("Journal", stat.journal || "—")],
      ["ETA", factValue("ETA", stat.eta || "—")],
      ["To do", todo || factValue("To do", "—")],
    ];
    const tab = el("table", "stab");
    rows.forEach(([k, v]) => {
      const text = (v && v.nodeType) ? "" : String(v || "").trim();
      const dim = !(v && v.nodeType) && (!text || text === "—");
      const flag = k === "Blocker" && text && text !== "none" && text !== "—";
      const tr = el("tr", flag ? "flag" : "");
      tr.appendChild(el("th", "", k));
      const td = el("td", dim ? "dim" : "");
      td.dataset.statusFact = k.toLowerCase();
      if (v && v.nodeType) td.appendChild(v);
      else {
        const span = el("span", "", text || "—");
        span.title = String(v || "");
        td.appendChild(span);
      }
      tr.appendChild(td);
      tab.appendChild(tr);
    });
    const compact = el("div", "status-compact");
    // the lead (one server template: next and why, and who it waits on) — first, before the locked rows
    const leadText = stat.lead_line || "Next not stated by the steward";
    const leadEl = el("div", "slead" + (stat.lead_line && stat.lead_line.indexOf("Next:") === 0 ? "" : " dim"), leadText);
    leadEl.dataset.statusFact = "lead";
    leadEl.title = leadText;
    compact.appendChild(leadEl);
    compact.appendChild(tab);   // the ten locked rows stay open below the lead (John, 2026-09-11: wording, not hiding)
    if (stat.latest_event && stat.latest_event.summary) {
      const latest = el("p");
      latest.dataset.statusFact = "latest";
      latest.appendChild(el("strong", "", "Latest "));
      latest.appendChild(el("span", "", oneLine(stat.latest_event.summary, 90) +
        " · " + new Date(stat.latest_event.at).toLocaleString()));
      compact.appendChild(latest);
    }
    const ask = el("div", "action-needed");
    ask.dataset.statusAction = "1";
    compact.appendChild(ask);
    body.appendChild(compact);
    paintActionNeeded(ask);
    if (p.goal_reread === false)
      body.appendChild(el("div", "splan sflag", "goal not re-read since last close"));
    b.appendChild(body);
    // (2026-09-05, John) the NEWEST status is always prominent: it carries
    // .latest, older blocks above it are folded to their time line, and the
    // pane always brings the newest into view (a status pane is for now,
    // not for reading history — history stays one click away).
    let history=s.querySelector('[data-statushistory]');
    if(!history){history=el('details','status-history');history.dataset.statushistory='1';history.appendChild(el('summary','','Earlier updates'));s.appendChild(history);}
    s.querySelectorAll(".blk.status.latest").forEach(o => {o.classList.remove("latest");history.appendChild(o);});
    b.classList.add("latest");
    s.insertBefore(b,s.firstChild);
    syncCompactActivity(lastState);
    s.scrollTop=0;
    // the window's header carries the time of the last update (idle projects
    // show their LAST update, stamped, not a fresh blank)
    const stamp = $("[data-statusstamp]");
    if (stamp) stamp.textContent = "last update " + hhmm + (stat.stale ? " · idle" : "");
    // the top bar is the ONE-LINE status of record for this steward run
    // (John, 2026-09-03); the goal moves inside the bar, one click away
    try {
      const brief = $("[data-goalbrief]"), lab = $("[data-goallabel]");
      if (brief) {
        // the lead (the one server template) is the line of record
        let line = stat.lead_line || "Next not stated by the steward";
        if (!p.waiting_on_you && stat.eta) line += " · ETA " + stat.eta;
        if (line.length > 120) line = line.slice(0, 117).replace(/\s+\S*$/, "") + "…";
        _statusLine = line + (stat.stale ? "  (" + hhmm + ")" : "");
        brief.textContent = _statusLine;
        if (lab) lab.textContent = "Status";
      }
    } catch (e) { /* no-op */ }
    // Deliverables tile stays pinned FIRST in the pane (2026-08-25, John's ask),
    // and its register refreshes on the same cadence as the status it sits above.
    try {
      // the tile owns [data-delivmount] above this scrollport; only pages
      // without that slot still need it pinned first INSIDE the pane
      if (!$("[data-delivmount]")) {
        const dt = s.querySelector(".blk.deliv");
        if (dt && s.firstChild !== dt) s.insertBefore(dt, s.firstChild);
      }
      renderDeliverablesTile();
    } catch (e) { /* no-op */ }
    // Render receipt (2026-08-25; COALESCED same day after review): the status is
    // now ON JOHN'S SCREEN — tell the engine so delivery is a receipt, not a hope
    // (wakeup-delivery lesson). poll() replays the whole event buffer on open, so
    // acks coalesce to ONE for the NEWEST rendered status (800ms debounce) — never
    // a burst per historical event. Fire-and-forget; failures never touch the pane.
    try {
      renderStatus._ackAt = stat.at || "";
      clearTimeout(renderStatus._ackTimer);
      renderStatus._ackTimer = setTimeout(() => {
        try { post(api("/api/status-ack"), { at: renderStatus._ackAt }).catch(() => {}); }
        catch (e) { /* no-op */ }
      }, 800);
    } catch (e) { /* no-op */ }
  }

  /* ---------- deliverables (2026-08-25, John's ask — journal 0010) ----------
     ONE source: the effort's DELIVERABLES.md register (the steward's own
     convention). Surfaced twice: a folded tile pinned at the very TOP of the
     status pane, and links inside the goal/map expansion. Openable entries
     stream through the contained /api/deliverable-file route; entries pointing
     outside the effort render as text, never links. */
  let _delivBusy = false;
  // per-step embedding (John, 2026-08-26: "embed the work products in the
  // plan flow"): register rows may carry an optional Step column — a step
  // NUMBER or a name fragment — and the map paints the link UNDER that step.
  let _deliv = {items: [], approved: [], acts: [], warning: ""}, _lastMap = null, _refinementContext = null, _answerQuestionId = null;
  let _delivOpen = (() => {
    try { return localStorage.getItem("steward_deliv_open") === "1"; }
    catch (e) { return false; }
  })();
  function stepDeliverables(step, idx1) {
    const steps=Array.isArray(_lastMap?.steps)?_lastMap.steps:[step];
    return _deliv.items.filter((it) => {
      const owner=navOwner(steps,it);
      return owner===step||!!owner&&typeof owner.id==='string'&&!!owner.id&&owner.id===step.id;
    });
  }
  // One blue SENTENCE under its step. Click once → the detail; click the
  // detail's link → the report itself (John's two-stage disclosure).
  function stepDelivLine(it) {
    const key = (it.dir || "") + "|" + (it.managed ? it.step + "|" + it.product_id : (it.path || it.what || ""));
    const row = el("div", "sdrow");
    const one = (it.what || "").split(" — ")[0].trim() || it.what || "(untitled)";
    const line = el("div", "sdone", "▸ " + one);
    try { const im = window.SkillIcons && window.SkillIcons.img(one, 14); if (im) line.insertBefore(im, line.firstChild); } catch (e) { /* no-op */ }
    const detail = el("div", "sddetail");
    if (it.managed) detail.style.overflowWrap = "anywhere";
    const full = el("div", "", it.what || "");
    detail.appendChild(full);
    if (it.date) detail.appendChild(el("div", "sdmeta", it.date));
    detail.appendChild(delivRow(it));           // the actual open link
    if (it.history && it.history.length) {
      const history = document.createElement("details");
      history.open = _openHistories.has(key);
      history.addEventListener("toggle", () => {
        if (!history.isConnected) return;
        if (history.open) _openHistories.add(key);
        else _openHistories.delete(key);
      });
      const summary = document.createElement("summary");
      summary.textContent = "Earlier versions · " + it.history.length + " presented";
      history.appendChild(summary);
      it.history.forEach((version) => {
        const labelled = Object.assign({}, version, {what: version.what + (version.accepted ? " · accepted" : "")});
        history.appendChild(delivRow(labelled));
      });
      detail.appendChild(history);
    }
    // the detail already carries the full description above; the link itself
    // just says what it does (2026-09-03)
    const lnk = detail.querySelector(".drow a");
    // a route row is labelled by the document it opens (report.md), never the
    // whole route string (2026-09-05, seen on the page)
    if (lnk) lnk.textContent = it.managed ? "Open current version" : "Open ↗" +
      (it.path ? "  " + it.path : (it.route ? "  " + routeName(it.route) : ""));
    row.dataset.key = key;
    if (_openDelivs.has(key)) row.classList.add("open");
    line.onclick = (ev) => {
      ev.stopPropagation();
      row.classList.toggle("open");
      if (row.classList.contains("open")) _openDelivs.add(key);
      else _openDelivs.delete(key);
    };
    // the detail's own clicks (its link, its text) never toggle the row or the step
    detail.onclick = (ev) => { ev.stopPropagation(); };
    row.appendChild(line);
    row.appendChild(detail);
    return row;
  }
  // What the USER opened, kept across repaints. paintStepsList rebuilds every
  // <li> and it runs on every map-stamp change (the steward rewrites the map
  // constantly) and on every register load — without this, a click collapsed
  // again within seconds.
  const _openSteps = new Set(), _openDelivs = new Set(), _openHistories = new Set();
  function producerHandoffs(handoffs, label, key) {
    const history = el("details", "sdmeta");
    history.open = _openHistories.has(key);
    history.ontoggle = () => history.open ? _openHistories.add(key) : _openHistories.delete(key);
    history.appendChild(el("summary", "", handoffs.length + " " + label));
    handoffs.forEach((h) => history.appendChild(el("div", "", (h.source_ref || h.handoff_id) + " · " + (h.terminal || "outcome unknown") + " · " + h.freshness + " · " + (h.at || ""))));
    return history;
  }
  /* Course/product navigation: one event-derived organization for both views. */
  const navStorageKey = () => 'steward_navigation:' + (window.STEWARD_PID || '') + ':' + DIR;
  let navChoices = null;
  function navChoice(key, fallback) {
    if (!navChoices) { try { navChoices=JSON.parse(localStorage.getItem(navStorageKey())||'{}'); } catch(e) { navChoices={}; } }
    return Object.prototype.hasOwnProperty.call(navChoices,key) ? navChoices[key] : fallback;
  }
  function navDisclosure(key, title, open=false, mark=null) {
    const d=el('details','navgroup'), summary=el('summary','');
    if (mark) summary.appendChild(el('span','plan-mark '+mark.cls, mark.glyph));
    summary.appendChild(document.createTextNode((mark ? ' ' : '') + title));
    d.dataset.navGroup=key;summary.dataset.navFocus='group:'+key;
    d.open=navChoice(key,open);d.appendChild(summary);
    const save=value=>{navChoices[key]=value;try{localStorage.setItem(navStorageKey(),JSON.stringify(navChoices));}catch(e){}};
    summary.addEventListener('click',()=>save(!d.open));
    d.addEventListener('toggle',()=>{if(d.isConnected)save(d.open);});
    return d;
  }
  function navOwner(steps, item) {
    steps=Array.isArray(steps)?steps:[];
    const stable=owner=>owner&&typeof owner.id==='string'&&owner.id.trim()&&
      steps.filter(s=>String(s.id||'').toLowerCase()===owner.id.toLowerCase()).length===1?owner:null;
    if(Object.prototype.hasOwnProperty.call(item,'owner_step_id')) {
      return typeof item.owner_step_id==='string'
        ? stable(steps.find(s=>s.id===item.owner_step_id)) : null;
    }
    const key=String(item.step||'').trim().toLowerCase();
    if(!key)return null;
    const ids=steps.filter(s=>String(s.id||'').trim().toLowerCase()===key);
    if(ids.length)return ids.length===1?stable(ids[0]):null;
    if(/^\d+$/.test(key))return stable(steps[Number(key)-1]);
    const names=steps.filter(s=>String(s.name||'').toLowerCase().includes(key));
    return names.length===1?stable(names[0]):null;
  }
  function navModel(map, items) {
    map=map&&typeof map==='object'?map:{};
    const steps=Array.isArray(map.steps)?map.steps:[];
    items=Array.isArray(items)?items:[];
    const fallback=map.navigation_fallback||{},fallbackRoot=fallback.root||fallback;
    const hasNavigation=steps.some(s=>s.navigation&&Array.isArray(s.navigation.path));
    const roots=[],all=new Map(),stepGroups=new Map(),relatedGroups=new Map(),overrides=new Map(),definitions=new Map(),featured=new Set();
    const stepIdCounts=new Map();
    steps.forEach(s=>{const id=typeof s.id==='string'?s.id.trim().toLowerCase():'';if(id)stepIdCounts.set(id,(stepIdCounts.get(id)||0)+1);});
    const pathKey=p=>String(p||'').replace(/\\/g,'/').toLowerCase();
    const addDefinition=g=>{
      if(g&&typeof g.id==='string'&&g.id)definitions.set(g.id,{...g,label:String(g.label||g.id),order:Number.isFinite(g.order)?g.order:0});
    };
    (Array.isArray(fallback.groups)?fallback.groups:[]).forEach(addDefinition);
    const rootId=typeof fallbackRoot.id==='string'&&fallbackRoot.id?fallbackRoot.id:!hasNavigation?'campaign-root':null;
    if(rootId)addDefinition({id:rootId,label:fallbackRoot.label||map.name||map.title||'Project work',order:0});
    steps.forEach(s=>(Array.isArray(s.navigation?.groups)?s.navigation.groups:[]).forEach(addDefinition));
    steps.forEach(s=>(Array.isArray(s.navigation?.featured_paths)?s.navigation.featured_paths:[]).forEach(p=>featured.add(pathKey(p))));
    const safePath=p=>Array.isArray(p)&&p.length>0&&p.length<=2&&p.every(g=>typeof g==='string'&&definitions.has(g));
    function ensure(path) {
      if(!safePath(path)){
        addDefinition({id:'unclassified',label:'Other work — needs organization',order:99999});
        path=rootId?[rootId,'unclassified']:['unclassified'];
      }
      let parent=null;
      for(const gid of path) {
        const g=definitions.get(gid);
        let node=all.get(g.id);
        if(!node){node={...g,children:[],steps:[],items:[],referenceSteps:[],referenceItems:[],parent,pinned:false};all.set(g.id,node);(parent?parent.children:roots).push(node);}
        parent=node;
      }
      return parent;
    }
    if(rootId){
      ensure([rootId]);
      (Array.isArray(fallback.components)?fallback.components:[]).forEach((component,i)=>{
        if(!component||typeof component.id!=='string'||!component.id||component.id===rootId)return;
        if(!definitions.has(component.id))addDefinition({id:component.id,label:component.name||component.id,order:i});
        ensure([rootId,component.id]);
      });
    }
    steps.forEach((s,i)=>{
      const n=s.navigation||{};
      let path=n.path;
      if(!hasNavigation){
        const stableId=typeof s.id==='string'?s.id.trim():'';
        if(stableId&&stepIdCounts.get(stableId.toLowerCase())===1){
          const id='compat-step:'+stableId;
          addDefinition({id,label:s.name||stableId,order:i});path=[rootId,id];
        } else path=null;
      }
      const group=ensure(path);group.steps.push({step:s,index:i});stepGroups.set(s,group);
      if(n.pin)for(let g=group;g;g=g.parent)g.pinned=true;
      (Array.isArray(n.include_paths)?n.include_paths:[]).forEach(ensure);
      const references=[];
      (Array.isArray(n.related_paths)?n.related_paths:[]).forEach(p=>{
        const related=ensure(p);
        if(related===group||references.includes(related))return;
        related.referenceSteps.push({step:s,index:i});references.push(related);
      });
      relatedGroups.set(s,references);
      (Array.isArray(n.items)?n.items:[]).forEach(o=>{if(typeof o.source_path==='string')overrides.set(pathKey(o.source_path),ensure(o.path));});
    });
    items.forEach(it=>{
      const owner=navOwner(steps,it);
      const group=overrides.get(pathKey(it.path))||(owner&&stepGroups.get(owner))||ensure(null);
      group.items.push(it);
      (owner?relatedGroups.get(owner)||[]:[]).forEach(related=>{
        if(related!==group&&!related.referenceItems.includes(it))related.referenceItems.push(it);
      });
    });
    const itemOrder=(a,b)=>Number(!!b.managed)-Number(!!a.managed)||String(b.date||'').localeCompare(String(a.date||''));
    const sortNodes=nodes=>{nodes.sort((a,b)=>(a.order-b.order)||a.label.localeCompare(b.label));nodes.forEach(n=>{sortNodes(n.children);n.items.sort(itemOrder);n.referenceItems.sort(itemOrder);});};
    sortNodes(roots);return {roots,all,featured};
  }
  function navFile(it, surface, readOnly=false) {
    const box=el('div','navfile');box.dataset.navPath=it.path||it.route||it.what;box.dataset.productId=it.product_id||'';
    const shown={...it,date:String(it.date||'').split('T')[0]};
    if(it.managed)shown.what=String(it.what||it.product_id).replace(/-/g,' ');
    const row=delivRow(shown);row.classList.add('navfilelink');box.appendChild(row);
    if(it.managed) {
      const round=it.round===0?'Initial draft':Number.isInteger(it.round)?'Refinement '+it.round:'';
      box.appendChild(el('div','sdmeta',it.accepted?'✓ Approved':it.accepted_current?'✓ Accepted version':
        [round,it.provisional?'Provisional draft':String(it.phase||'').replace(/_/g,' ')].filter(Boolean).join(' · ')));
      if(!readOnly && !it.accepted && !it.accepted_current && it.presentation_id) {
        const accept=el('button','nav-accept','Done with this item');
        accept.title='Approve only '+it.product_id+' · '+round;
        accept.onclick=async()=>{
          accept.disabled=true;
          try {
            const response=await post('/api/refinement-accept',{step_id:it.step,presentation_id:it.presentation_id,
              product_id:it.product_id,revision_id:it.revision_id,hash:it.hash});
            const result=await response.json();if(!response.ok||!result.ok)throw Error(result.error||'Approval failed');
            await loadMap();await renderDeliverablesTile();
          } catch(error) {box.appendChild(el('div','sdmeta',error.message));accept.disabled=false;}
        };
        box.appendChild(accept);
      }
      if(!readOnly && !it.accepted && it.presentation_id) {
        const refine=el('button','nav-refine','Request changes');
        refine.onclick=()=>{_answerQuestionId=null;_refinementContext={step_id:it.step,presentation_id:it.presentation_id,product_id:it.product_id};
          const ta=$('[data-say]');if(ta){ta.placeholder='Changes for '+it.product_id;ta.focus();}};
        box.appendChild(refine);
      }
    }
    const a=row.querySelector('a');if(a)a.dataset.navFocus=surface+':file:'+(it.path||it.route||it.what);
    if(it.history&&it.history.length) {
      const h=navDisclosure(surface+':versions:'+it.step+':'+it.product_id,'Earlier versions · '+it.history.length);
      it.history.slice().sort((a,b)=>String(b.date||'').localeCompare(String(a.date||''))).forEach(v=>h.appendChild(delivRow(v)));
      box.appendChild(h);
    }
    return box;
  }
  function navStyle() {
    if(document.getElementById('course-navigation-style'))return;
    const s=el('style');s.id='course-navigation-style';
    s.textContent=`.navtree{min-width:0;font-size:13px;line-height:1.42}.navgroup{margin:5px 0;border-top:1px solid #ffffff20;min-width:0}.navgroup>summary{cursor:pointer;padding:8px 3px;font-weight:600;white-space:normal;overflow-wrap:anywhere}.navcontents{padding:0 0 5px 9px;min-width:0}.navgroup .navgroup .navcontents{padding-left:7px}.navfile{padding:5px 0;overflow-wrap:anywhere;border-bottom:1px solid #ffffff0b}.navfile .drow{white-space:normal;overflow:visible;font-size:13px;line-height:1.42}.navfile a{white-space:normal;overflow-wrap:anywhere}.navpin{padding:10px;margin:0 0 10px;border:1px solid #679cc077;border-radius:6px;background:#44698718}.navpin-title{font-size:14px;font-weight:600;margin:3px 0}.naveyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.06em;opacity:.8}.navstep-list{padding:0!important;list-style:none}.navstep-list>li{padding:6px 0!important}.navstep-list .sdeliv{display:none}.navstep-list .sdeliv:has(button){display:block}.navempty{opacity:.75;padding:5px 0;font-size:12px}.navtree .navsupport{margin-top:7px}.navtree .navsupport>summary{font-size:12px;font-weight:400}.navtree .wpkind{display:none}.navtree .navstep-list .stitle{white-space:normal}.navtree .navstep-list .sdmeta{font-size:12px}.navtree .navfile .navgroup{font-size:12px}.navtree .navfile .navgroup>summary{padding:3px;font-weight:400}`;
    s.textContent+='[data-delivmount] .blk.deliv:not(.folded)>.body{max-height:min(52vh,500px);overflow-y:auto;overflow-x:hidden;overscroll-behavior:contain;padding-right:6px}';
    document.head.appendChild(s);
  }
  function renderNavigation(target,map,items,surface,stepRows=null) {
    const model=navModel(map,items);if(!model && stepRows)return false;navStyle();target.classList.add('navtree');
    const pin=(map?.steps||[]).find(s=>s.navigation&&s.navigation.pin);
    if(!stepRows) {
      const p=el('div','navpin');p.appendChild(el('div','naveyebrow','Current work and review'));
      // Do now: the open decision, each product awaiting review, the current step's files, then the steward's next
      const acts=[];
      const q=currentQuestion();
      if(q&&q.question)acts.push({act:'Answer',label:String(q.question).slice(0,80),question:q});
      (_deliv.acts||[]).forEach(a=>acts.push(a));
      const doNow=el('div','navacts');doNow.appendChild(el('div','navactshead','Do now'));
      if(_deliv.warning)doNow.appendChild(el('div','navempty',_deliv.warning));   // A2: the current item, honestly
      acts.forEach(a=>{
        const row=el('div','navact navact-'+a.act.toLowerCase());
        row.appendChild(el('span','navactkind',a.act));
        if(a.act==='Answer'){const b=el('button','navactbtn',a.label);b.onclick=()=>openQuestionContext(a.question&&a.question.id);row.appendChild(b);}
        else if(a.item){row.appendChild(navFile(a.item,surface+':act'));}
        else if(a.path){row.appendChild(navFile({what:a.label,path:a.path,openable:true,step:a.step},surface+':act'));}
        else row.appendChild(el('span','navactlabel',a.label));
        doNow.appendChild(row);
      });
      if(!acts.length)doNow.appendChild(el('div','navempty','Nothing waits on you; the steward has not stated a next step.'));
      p.appendChild(doNow);
      const acted=new Set(acts.map(a=>a.path).filter(Boolean));
      const current=items.filter(i=>i.is_current===true&&!acted.has(i.path))   // the server's one rule, minus what is already an act
        .sort((a,b)=>String(b.date||'').localeCompare(String(a.date||'')));
      if(current.length){
        const files=navDisclosure(surface+':files','Files awaiting you · '+current.length);
        current.forEach(it=>files.appendChild(navFile(it,surface+':pin')));
        p.appendChild(files);
      }
      target.appendChild(p);
      const approved=navDisclosure(surface+':approved','Approved deliverables · '+_deliv.approved.length);
      _deliv.approved.slice().sort((a,b)=>String(b.date||'').localeCompare(String(a.date||'')))
        .forEach(it=>approved.appendChild(navFile(it,surface+':approved')));
      if(!_deliv.approved.length)approved.appendChild(el('div','navempty','No explicitly approved deliverables yet.'));
      target.appendChild(approved);
    }
    if(!model) {
      const rest=navDisclosure(surface+':all','All deliverables');
      items.forEach(it=>rest.appendChild(navFile(it,surface+':all')));target.appendChild(rest);
      return true;
    }
    const groupSteps=g=>{
      const unique=new Map();
      g.steps.concat(g.referenceSteps||[],g.children.flatMap(groupSteps)).forEach(s=>{
        const key='index:'+s.index;
        if(!unique.has(key))unique.set(key,s);
      });
      return [...unique.values()];
    };
    const groupMarkInfo=g=>{
      const required=groupSteps(g).filter(s=>s.step.navigation?.role==='primary');
      const steps=required.length?required:groupSteps(g);
      if(!steps.length) return {glyph:'▷',cls:'todo'};
      if(steps.every(s=>stepDone(s.step))) return {glyph:'✓',cls:'done'};
      if(steps.some(s=>stepNeedsAttention(s.step))) return {glyph:'⚑',cls:'flag'};
      return {glyph:'▷',cls:'todo'};
    };
    function renderReferences(g,parent,refSurface) {
      const steps=g.referenceSteps||[],items=g.referenceItems||[];
      if(!steps.length&&!items.length)return;
      const shared=navDisclosure(refSurface+':shared:'+g.id,'Shared work and deliverables');
      if(steps.length){
        const list=el('ul','navstep-list');
        steps.forEach(s=>{
          const row=el('li','navstep-reference'),done=stepDone(s.step),attention=stepNeedsAttention(s.step);
          row.dataset.stepRef=s.step.id||String(s.index);
          row.appendChild(el('span','plan-mark '+(done?'done':attention?'flag':'todo'),done?'✓':attention?'⚑':'▷'));
          row.appendChild(document.createTextNode(' '+(s.step.name||s.step.id||'Step '+(s.index+1))));
          list.appendChild(row);
        });
        shared.appendChild(list);
      }
      items.forEach(it=>shared.appendChild(navFile(it,refSurface+':reference:'+g.id,true)));
      parent.appendChild(shared);
    }
    function renderGroup(g,parent) {
      // the sequence stays open; done, parked and supporting steps fold (John, 2026-09-19: "a mess of flags")
      const offPath=st=>stepDone(st)||st.status==='parked';
      const actives=g.steps.filter(s=>s.step.status==='active');
      const pinned=g.steps.some(s=>s.step.navigation&&(s.step.navigation.pin||s.step.navigation.current));
      const title=g.label+(actives.length>1&&!pinned?' · '+actives.length+' active — pin one':'');
      const d=navDisclosure(surface+':'+g.id,title,false,groupMarkInfo(g)),body=el('div','navcontents');
      d.dataset.groupId=g.id;
      if(stepRows) {
        const main=g.steps.filter(s=>s.step.navigation&&s.step.navigation.role==='primary'&&!offPath(s.step));
        if(main.length) {const list=el('ul','navstep-list');main.forEach(s=>{const row=stepRows.get(s.index);if(row)list.appendChild(row);});body.appendChild(list);}
      }
      g.children.forEach(child=>renderGroup(child,body));
      const mainFiles=g.items.filter(it=>it.managed||model.featured.has(String(it.path||'').replace(/\\/g,'/').toLowerCase()));
      const shown=g.items.length<=6?g.items:mainFiles.length?mainFiles:g.items.slice(0,3);
      const rest=g.items.filter(it=>!shown.includes(it));
      shown.forEach(it=>body.appendChild(navFile(it,surface)));
      if(rest.length){const more=navDisclosure(surface+':materials:'+g.id,'Earlier work and supporting materials · '+rest.length);rest.forEach(it=>more.appendChild(navFile(it,surface)));body.appendChild(more);}
      renderReferences(g,body,surface);
      if(stepRows) {
        const support=g.steps.filter(s=>!s.step.navigation||s.step.navigation.role!=='primary'||offPath(s.step));
        if(support.length){const more=navDisclosure(surface+':support:'+g.id,'Done, parked and supporting steps · '+support.length),list=el('ul','navstep-list');more.classList.add('navsupport');support.forEach(s=>{const row=stepRows.get(s.index);if(row)list.appendChild(row);});more.appendChild(list);body.appendChild(more);}
      } else if(!g.items.length&&!g.referenceItems.length&&!g.referenceSteps.length&&!g.children.length)body.appendChild(el('div','navempty','No deliverables registered yet.'));
      d.appendChild(body);parent.appendChild(d);
    }
    if(stepRows)model.roots.forEach(g=>renderGroup(g,target));
    else {
      const choose=el('div','nav-select'), detail=el('section','nav-inspect');
      detail.setAttribute('aria-label','Selected group deliverables');
      const key=surface+':selected';let selected=navChoice(key,model.roots[0]?.id);
      if(!model.all.has(selected))selected=model.roots[0]?.id;
      const buttons=[];
      function inspect(id){
        const g=model.all.get(id);if(!g)return;
        selected=id;navChoices[key]=id;try{localStorage.setItem(navStorageKey(),JSON.stringify(navChoices));}catch(e){}
        buttons.forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.groupId===id)));
        detail.textContent='';detail.appendChild(el('h3','',g.label));
        if(g.parent)detail.appendChild(el('div','sdmeta',g.parent.label));
        const main=g.items.filter(it=>it.managed||model.featured.has(String(it.path||'').replace(/\\/g,'/').toLowerCase()));
        const shown=g.items.length<=6?g.items:main.length?main:g.items.slice(0,3);
        shown.forEach(it=>detail.appendChild(navFile(it,surface+':selected')));
        const rest=g.items.filter(it=>!shown.includes(it));
        if(rest.length){const more=navDisclosure(surface+':support:'+g.id,'Earlier work and supporting materials · '+rest.length);
          rest.forEach(it=>more.appendChild(navFile(it,surface+':support')));detail.appendChild(more);}
        renderReferences(g,detail,surface+':selected');
        g.children.forEach(child=>{
          const mark=groupMarkInfo(child), b=el('button','nav-child');
          b.appendChild(el('span','plan-mark '+mark.cls, mark.glyph));
          b.appendChild(document.createTextNode(' '+child.label));
          b.onclick=()=>inspect(child.id);detail.appendChild(b);
        });
        if(!g.items.length&&!g.referenceItems.length&&!g.referenceSteps.length&&!g.children.length)detail.appendChild(el('div','navempty','No deliverables registered yet.'));
      }
      function choice(g,parent){
        const mark=groupMarkInfo(g), b=el('button','nav-choice');
        b.appendChild(el('span','plan-mark '+mark.cls, mark.glyph));
        b.appendChild(document.createTextNode(' '+g.label));
        b.dataset.groupId=g.id;
        b.dataset.navFocus=surface+':select:'+g.id;b.onclick=()=>inspect(g.id);buttons.push(b);parent.appendChild(b);
        if(g.children.length){const children=navDisclosure(surface+':choose:'+g.id,'Sections and deliverables');g.children.forEach(c=>choice(c,children));parent.appendChild(children);}}
      model.roots.forEach(g=>choice(g,choose));target.appendChild(choose);target.appendChild(detail);inspect(selected);
    }
    return true;
  }
  function restoreNavFocus(key) {
    if(!key)return;
    const e=Array.from(document.querySelectorAll('[data-nav-focus]')).find(n=>n.dataset.navFocus===key);
    if(e)e.focus({preventScroll:true});
  }

  function paintStepsList(map) {
    const list = $("[data-steps]");
    if (!list) return;
    const focusKey=document.activeElement && document.activeElement.dataset.navFocus;
    const stepRows=new Map();
    list.textContent = "";
    const unmapped = Object.values(((map.refinement || {}).state || {}).producer_handoffs || {}).filter((h) => !h.step_id && h.status === "pending_steward_review");
    if (unmapped.length) {
      const row = el("li", "waiting");
      row.appendChild(producerHandoffs(unmapped, "work item(s) need Steward to identify their slice", "handoffs:unmapped"));
      list.appendChild(row);
    }
    map.steps.forEach((st, i) => {
      const info = planMarkInfo(st);
      const li = el("li", info.row);
      li.dataset.stepId=st.id;stepRows.set(i,li);
      li.appendChild(el("span", "mark " + info.cls, info.glyph));
      const wrap = el("div");
      // a flex item defaults to min-width:auto, which nowrap text resolves to
      // the full string width — the rail then grows a horizontal scrollbar
      // instead of ellipsizing the blue line
      wrap.style.minWidth = "0";
      // (2026-09-06, John) the TITLE line is the only toggle; a ▸/▾ twisty says the state
      const title = el("div", "stitle");
      title.appendChild(el("span", "tw", ""));
      if (st.part) title.appendChild(el("span", "wpkind", st.part));
      // (2026-09-05, John) a step that names a skill carries its mark
      try {
        const _sk = window.SkillIcons && window.SkillIcons.img((st.commissioned_as || "") + " " + st.name, 16);
        if (_sk) title.appendChild(_sk);
      } catch (e) { /* no-op */ }
      title.appendChild(document.createTextNode((st.navigation && st.navigation.label) || st.name));
      wrap.appendChild(title);
      if (st.refinement) {
        const r = st.refinement;
        const shownRound=r.display_round??r.round;
        const label = shownRound === 0 ? "Initial draft" : "Refinement " + shownRound;
        wrap.appendChild(el("div", "sdmeta", label + " · " + r.phase.replace(/_/g, " ") + " · " + shownRound + " refinements"));
        (r.depends_on || []).forEach((d) => {
          const foundation=map.steps.find(s=>s.id===d.slice_id);
          wrap.appendChild(el("div", "sdmeta", "Foundation: " + (foundation?.name||d.slice_id) + ' · ' + d.state.replace(/_/g, " ") +
            (d.reason?' — '+d.reason:'')));
        });
        const current = (r.presentations || []).slice(-1)[0];
        const handoffs = r.producer_handoffs || [];
        if (handoffs.length) {
          wrap.appendChild(producerHandoffs(handoffs, "work item(s) awaiting Steward review", "handoffs:" + st.id));
        }
        if (current) {
          const actions = el("div", "sdeliv");
          const refine = el("button", "", "Refine this slice");
          refine.onclick = (event) => {
            event.stopPropagation();
            _refinementContext = {step_id: st.id, presentation_id: current.id};
            const composer = $("[data-say]");
            if (composer) { composer.placeholder = "Changes for " + st.name; composer.focus(); }
          };
          actions.appendChild(refine);
          if (r.phase === "awaiting_review") {
            const done = el("button", "", "Done with this slice");
            done.onclick = async (event) => {
              event.stopPropagation(); done.disabled = true;
              try {
                const response = await post("/api/refinement-close", {step_id: st.id, presentation_id: current.id});
                const result = await response.json();
                if (!response.ok || !result.ok) throw new Error(result.error || "Close failed");
                await loadMap();
              } catch (error) { actions.appendChild(el("span", "sdmeta", error.message)); done.disabled = false; }
            };
            actions.appendChild(done);
          }
          wrap.appendChild(actions);
        }
      }
      const parts = [];
      // live feedback rides the map: the active step says what is
      // happening now; waiting steps say what they wait on
      if (st.status === "active") {
        const live = map.attention.state === "working"
          ? (map.attention.reason || "running now")
          : (map.heartbeat.next_recommended || "");
        if (live) parts.push("now: " + live.replace(/\*\*/g, ""));
      }
      if (st.status === "waiting" && st.waiting_on)
        parts.push("waiting on: " + st.waiting_on);
      if (st.done_when) parts.push("done when: " + st.done_when);
      if (st.commissioned_as) parts.push("ran as: " + st.commissioned_as);
      // no filler: a step with nothing recorded shows nothing
      if (parts.length) wrap.appendChild(el("div", "why", parts.join("\n")));
      // The plan must stay SCANNABLE (John, 2026-08-26: "it should not open
      // up and give me all the details ... has to be really tight and tidy").
      // Three levels, each a deliberate click:
      //   1. step name (+ a one-SENTENCE blue line per deliverable)
      //   2. click the step  -> its why/done-when detail
      //   3. click a deliverable -> its detail, click again -> the report
      const dl = stepDeliverables(st, i + 1);
      if (dl.length) {
        const box = el("div", "sdeliv");
        dl.forEach((it) => box.appendChild(stepDelivLine(it)));
        wrap.appendChild(box);
      }
      li.appendChild(wrap);
      const stepKey = st.id || st.name || String(i);
      if (_openSteps.has(stepKey)) li.classList.add("open");
      li.onclick = (ev) => {
        if (ev.target.closest(".sdeliv")) return;   // deliverables own their clicks
        if (!ev.target.closest(".stitle")) return;  // reading the detail never collapses it
        li.classList.toggle("open");
        if (li.classList.contains("open")) _openSteps.add(stepKey);
        else {
          _openSteps.delete(stepKey);
          // closing a step closes everything open under it (down and up the levels)
          li.querySelectorAll(".sdrow.open").forEach((r) => {
            r.classList.remove("open");
            if (r.dataset.key) _openDelivs.delete(r.dataset.key);
          });
        }
      };
      list.appendChild(li);
    });
    if (navModel(map,_deliv.items)) {
      const prior=Array.from(list.children).filter(n=>!n.dataset.stepId);
      list.textContent='';
      const host=el('li','navhost');host.style.display='block';host.style.padding='0';
      renderNavigation(host,map,_deliv.items,'plan',stepRows);list.appendChild(host);
      prior.forEach(n=>list.appendChild(n));restoreNavFocus(focusKey);
    }
  }
  async function renderDeliverablesTile() {
    if (_delivBusy) return;
    _delivBusy = true;
    let d = null;
    try { d = await (await fetch(api("/api/deliverables"))).json(); }
    catch (e) { _delivBusy = false; return; }
    _delivBusy = false;
    const items = (d && d.items) || [];
    const focusKey=document.activeElement && document.activeElement.dataset.navFocus;
    _deliv = {items, approved: (d && d.approved) || [], acts: (d && d.acts) || [], warning: (d && d.current_warning) || ""};
    // repaint the plan so step-tagged deliverables land under their steps
    if (_lastMap) { try { paintStepsList(_lastMap); } catch (e) {} }
    // — the tile: its OWN slot above the scrollport when the page provides
    //   one (never overlaps the status blocks), else the pane as before —
    const s = $("[data-delivmount]") || paneEl();
    if (s) {
      let tile = s.querySelector(".blk.deliv");
      const priorScroll=tile && tile.querySelector(".body") ? tile.querySelector(".body").scrollTop : 0;
      // starts CLOSED so the status keeps the room; his choice then sticks
      const wasOpen = tile ? !tile.classList.contains("folded")
                           : (_delivOpen === true);
      if (!tile) {
        tile = el("div", "blk steward deliv folded");
        s.insertBefore(tile, s.firstChild);
      } else tile.textContent = "";
      if (wasOpen) tile.classList.remove("folded");
      // one-line summary in the header, so a folded tile still tells him what
      // is in there (John, 2026-08-27: "deliverables on top with a little
      // summary above that")
      // "newest" must BE the newest: the register is parsed in file order and
      // its own convention (newest-first) is a convention, not a guarantee —
      // labelling items[0] as newest silently lied whenever a steward
      // appended. Pick by date, fall back to file order.
      const byDate = items.slice().sort((a, b) =>
        String(b.date || "").localeCompare(String(a.date || "")));
      const newest = byDate.length
        ? (byDate[0].what || "").split(" — ")[0].trim() : "";
      const who = el("div", "who",
        "📦 DELIVERABLES (" + items.length + ")" +
        (newest ? " — newest: " + newest : " — nothing registered yet"));
      if(navModel(_lastMap,items))who.textContent="DELIVERABLES · current and earlier work";
      who.style.cursor = "pointer";
      who.onclick = () => {
        tile.classList.toggle("folded");
        _delivOpen = !tile.classList.contains("folded");
        try { localStorage.setItem("steward_deliv_open",
                                   _delivOpen ? "1" : "0"); } catch (e) {}
      };
      tile.appendChild(who);
      const body = el("div", "body");
      if(d?.finished_projection && !d.finished_projection.consistent)
        body.appendChild(el('div','sdmeta','Finished Deliverables needs repair · '+(d.finished_projection.error||'projection incomplete')));
      if (!d || !d.exists) {
        body.appendChild(el("div", "snow", "No DELIVERABLES.md yet — the steward starts the register when the first human-facing artifact lands."));
      } else if (!items.length) {
        body.appendChild(el("div", "snow", "(register is empty)"));
      }
      // ONE line each (John, 2026-09-03): click → the long description →
      // click its link → the deliverable opens in a new window
      if (!renderNavigation(body,_lastMap,items,"deliverables")) items.forEach((it) => body.appendChild(stepDelivLine(it)));
      tile.appendChild(body);
      body.scrollTop=priorScroll;
      if (s.firstChild !== tile) s.insertBefore(tile, s.firstChild);
    }
    // — the goal/map links —
    const slot = $("[data-deliverables]");
    if (slot) {
      slot.textContent = "";
      if (items.length) {
        slot.appendChild(el("div", "glabel", "Deliverables"));
        if (!renderNavigation(slot,_lastMap,items,"map-deliverables")) items.forEach((it) => slot.appendChild(stepDelivLine(it)));
      }
    }
    restoreNavFocus(focusKey);
  }
  // (2026-09-05, John) a route opens rendered: markdown through the Reader,
  // Word / PowerPoint / Excel as a preview page; the page token rides along.
  function routeHref(route) {
    const r = String(route || "");
    const sep = r.indexOf("?") >= 0 ? "&" : "?";
    const md = /\.(md|markdown)(&|$)/i.test(r), office = /\.(docx|pptx|xlsx)(&|$)/i.test(r);
    return r + (md ? sep + "render=1" : office ? sep + "view=1" : "") +
      (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "");
  }
  function routeName(r) {
    try { const m = /[?&]path=([^&]+)/.exec(r); const seg = decodeURIComponent(m ? m[1] : r).split("/").filter(Boolean); return seg[seg.length - 1] || r; }
    catch (e) { return r; }
  }
  function delivRow(it) {
    const row = el("div", "snow drow");
    if (it.notebook_product && window.AnchorNotebooks) {
      row.appendChild(window.AnchorNotebooks.render(it, it.dir !== undefined ? it.dir : DIR));
      return row;
    }
    if (it.route) {
      // (2026-09-05) a contained Anchor route (/report/…, /artifact/…) the
      // parser CLASSIFIED (classify_route) — hostile cells arrive route:null
      // and fall through to the text branch. Opens in a new window with the
      // page token appended, same mechanism as the deliverable-file link.
      const a = document.createElement("a");
      // labelled by the document it opens, never the whole route (2026-09-05)
      a.textContent = "• " + (it.what || routeName(it.route));
      try { const im = window.SkillIcons && window.SkillIcons.img(it.what || "", 14); if (im) a.insertBefore(im, a.firstChild); } catch (e) { /* no-op */ }
      a.href = routeHref(it.route);
      a.target = "_blank";
      a.rel = "noopener";
      row.appendChild(a);
    } else if (it.openable && it.path) {
      const a = document.createElement("a");
      a.textContent = "• " + it.what;
      try { const im = window.SkillIcons && window.SkillIcons.img(it.what || "", 14); if (im) a.insertBefore(im, a.firstChild); } catch (e) { /* no-op */ }
      // 2026-08-26 (John: "I click on them and the page had nothing"): a raw
      // <a href> NAVIGATES — it never passes through the fetch shim, so the
      // old api() URL arrived with no /api/steward/ prefix, no pid and no
      // token → a blank page. Build the FULL authed URL ourselves, and send
      // text docs (.md/.txt/.csv/.json/.log) through the report VIEWER so
      // they render human-readable instead of as raw bytes.
      const dirRel = it.dir !== undefined ? it.dir : DIR;
      const isText = /\.(md|txt|csv|json|log)$/i.test(it.path);
      if (isText) {
        a.href = "#";
        a.onclick = (ev) => { ev.preventDefault();
          window.open("/report?dir=" + encodeURIComponent(dirRel) +
                      "&path=" + encodeURIComponent(it.path)); };
      } else {
        a.href = "/api/steward/deliverable-file?pid=" +
          encodeURIComponent(window.STEWARD_PID || "") +
          "&dir=" + encodeURIComponent(dirRel) +
          "&path=" + encodeURIComponent(it.path) +
          (it.hash ? "&hash=" + encodeURIComponent(it.hash) : "") +
          (/\.(docx|pptx|xlsx)$/i.test(it.path) ? "&view=1" : "") +
          (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "");
        a.target = "_blank";
        a.rel = "noopener";
      }
      row.appendChild(a);
      if(/\.pptx$/i.test(it.path)) {
        const download=el('a','sdmeta',' Download PowerPoint');
        download.href=a.href.replace(/&view=1\b/,'')+'&download=1';download.target='_blank';download.rel='noopener';row.appendChild(download);
      }
      if (it.managed && it.presentation_id) {
        const href = a.href;
        a.onclick = async (ev) => {
          ev.preventDefault();
          // Open the already-addressed file immediately. Recording the view is
          // bookkeeping and must not withhold or close the document (John,
          // 2026-09-14 and 2026-09-18: managed Current work opened about:blank,
          // waited on a slow view write, then closed the window).
          const preview = window.open("about:blank", "_blank");
          const target = isText ? "/steward/report?pid=" + encodeURIComponent(window.STEWARD_PID || "") + "&dir=" + encodeURIComponent(dirRel) + "&path=" + encodeURIComponent(it.path) + (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "") : href;
          if (preview) { preview.opener = null; preview.location = target; }
          else window.location.assign(target);
          try {
            const response = await post("/api/refinement-open", {
              step_id: it.step, presentation_id: it.presentation_id,
              product_id: it.product_id, session_id: String(window.STEWARD_TERM || "cockpit")
            });
            const result = await response.json();
            if (!response.ok || !result.ok) {
              if (!row.querySelector("[data-view-record-miss]")) {
                const note = el("span", "sdmeta", "Opened the file; viewing was not recorded.");
                note.dataset.viewRecordMiss = "1";
                row.appendChild(note);
              }
            }
          } catch (error) {
            if (!row.querySelector("[data-view-record-miss]")) {
              const note = el("span", "sdmeta", "Opened the file; viewing was not recorded.");
              note.dataset.viewRecordMiss = "1";
              row.appendChild(note);
            }
          }
        };
      }
    } else {
      row.appendChild(document.createTextNode("• " + it.what + (it.path ? " — " + it.path : "")));
    }
    // reports-links W3: a row carrying a run: command gets a 'Run ▶' control.
    // It POSTs the register-allowlisted command to the run endpoint (the server
    // re-reads the register and refuses anything else byte-for-byte), then
    // opens the EXISTING standalone terminal page on the returned session —
    // the command sits on the shell prompt UNSENT until the user presses
    // Enter. textContent only, never raw markup injection.
    if (it.run) {
      const runDir = it.dir !== undefined ? it.dir : DIR;
      const rbtn = document.createElement("a");
      rbtn.className = "drun";
      rbtn.textContent = " Run ▶";
      rbtn.href = "#";
      rbtn.title = "Open a terminal with this command staged (Enter runs it)";
      rbtn.onclick = (ev) => {
        ev.preventDefault();
        _postJson("/api/rnd/run_deliverable_terminal", {
          project_id: window.STEWARD_PID || "",
          dir: runDir,
          command: it.run,
        }).then((r) => r.json()).then((j) => {
          const sid = j && j.ok && j.session && j.session.session_id;
          if (!sid) return;
          window.open("/zombie_terminal?session=" + encodeURIComponent(sid) +
            (window.STEWARD_TOKEN
              ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : ""));
        }).catch(() => {});
      };
      row.appendChild(rbtn);
    }
    if (it.date) row.appendChild(document.createTextNode(" · " + it.date));
    return row;
  }

  /* ---------- live activity (replaces per-tool chatter) ---------- */
  let actEl = null, actSteps = [], actStart = 0, actTimer = null, actHome = null;
  function actLabel() {
    const secs = actStart ? Math.round((Date.now() - actStart) / 1000) : 0;
    const last = actSteps.length ? actSteps[actSteps.length - 1] : "";
    return "⟳ working — " + actSteps.length +
      (actSteps.length === 1 ? " step" : " steps") +
      (secs ? " · " + (secs < 90 ? secs + "s" : Math.round(secs / 60) + "m") : "") +
      (last ? " · " + last : "");
  }
  // Drop the live line WITHOUT touching the DOM (used when the transcript is
  // cleared on an epoch reconnect, and whenever a turn can no longer end).
  function resetActivity() {
    if (actTimer) { clearInterval(actTimer); actTimer = null; }
    // A tick turn's line lives in the STATUS pane, which the reconnect does
    // not clear. Dropping the pointer there left a node reading "⟳ working"
    // with no owner and no timer — a permanent false running indicator on the
    // pane John now sees by default. Finalize it before letting go.
    if (actEl && actEl.isConnected && actSteps.length) {
      const n = actSteps.length;
      actEl.classList.add("done");
      actEl.querySelector(".acthead").textContent =
        "✓ " + n + (n === 1 ? " step" : " steps") + " — click to see what it did";
    }
    actEl = null; actSteps = []; actStart = 0; actHome = null;
  }
  function activity(ev) {
    const step = (ev.name || "?") + (ev.detail ? " " + ev.detail : "");
    const s = targetFor(ev);
    // a tick-tagged tool goes to the status pane, a plain one to the
    // conversation: never keep appending into a line that lives elsewhere
    if (actEl && (actHome !== s || !actEl.isConnected)) endActivity(null);
    actSteps.push(step);
    if (!actEl) {
      const stick = atBottom(s);
      actStart = Date.now();
      actHome = s;
      const box = el("div", "blk act");        // capture the ELEMENT, not the
      const head = el("div", "acthead", "");   // module slot: endActivity nulls
      const body = el("div", "actbody");       // actEl and the old closure then
      head.onclick = () => box.classList.toggle("open");  // threw / hit the
      box.appendChild(head);                   // wrong line
      box.appendChild(body);
      s.appendChild(box);
      actEl = box;
      pin(s, stick);
      actTimer = setInterval(() => {
        if (!actEl || !actEl.isConnected) { resetActivity(); return; }
        actEl.querySelector(".acthead").textContent = actLabel();
      }, 1000);
    }
    actEl.querySelector(".acthead").textContent = actLabel();
    actEl.querySelector(".actbody").appendChild(el("div", "actstep", "· " + step));
    // stay at the bottom: prose blocks land after it, and a live indicator
    // stranded above the transcript answers nothing. ONLY when the reader is
    // already pinned to the bottom — relocating the node shifts everything
    // after it, which yanks the page for someone reading scrollback.
    const stick = atBottom(s);
    if (stick && actEl.nextSibling) s.appendChild(actEl);
    pin(s, stick);
  }
  function endActivity(ev) {
    if (actTimer) { clearInterval(actTimer); actTimer = null; }
    const box = actEl, n = actSteps.length;
    actEl = null; actSteps = []; actStart = 0; actHome = null;
    if (!box || !box.isConnected || !n) return;
    box.classList.add("done");
    box.querySelector(".acthead").textContent =
      "✓ " + n + (n === 1 ? " step" : " steps") +
      (ev && ev.duration_s ? " · " + (ev.duration_s < 90 ? ev.duration_s + "s"
        : Math.round(ev.duration_s / 60) + "m") : "") + " — click to see what it did";
  }

  /* ---------- events ---------- */
  function handle(ev) {
    if (ev.t === "delta") {
      const s = targetFor(ev);
      const stick = atBottom(s);
      if (!currentBlock || currentBlock._tick !== !!ev.tick) {
        closeCurrent();
        currentBlock = addBlock("steward", opts.stewardLabel || "ECGBERHT",
                                "", "", ev);
        currentBlock._raw = "";
        currentBlock._tick = !!ev.tick;
      }
      currentBlock._raw += ev.text;
      currentBlock.querySelector(".body").textContent = currentBlock._raw;
      if (stick) pin(s, true);
    } else if (ev.t === "john") {
      closeCurrent();
      addBlock("john", opts.johnLabel || "JOHN", ev.text);
      busySince = Date.now();
    } else if (ev.t === "tool") {
      // ONE live activity line, not a line per call (John, 2026-08-26: the
      // tool chatter buried what the steward was actually saying, and he
      // still couldn't tell whether it was running). The line updates in
      // place, counts the steps, names the current one, and expands to the
      // full list on click. It IS the running indicator.
      closeCurrent();
      activity(ev);
    } else if (ev.t === "turn_end") {
      closeCurrent();
      busySince = null;
      endActivity(ev);
      const hasReportedTurnCost = typeof ev.cost_usd === "number" && Number.isFinite(ev.cost_usd) && ev.cost_usd >= 0
        && (ev.cost_status === "reported" || ev.cost_status === undefined);
      const turnCostText = hasReportedTurnCost
        ? "$" + ev.cost_usd.toFixed(ev.cost_usd === 0 ? 2 : 3) + " reported"
        : "cost unavailable";
      const turnTokensText = typeof ev.tokens === "number" && Number.isFinite(ev.tokens) && ev.tokens >= 0
        ? " · " + Math.round(ev.tokens).toLocaleString() + " tokens" : "";
      addLine("turnend", "· turn done in " + ev.duration_s + "s · " + turnCostText + turnTokensText, ev);
      // Older live servers persist completion without publishing it. Coalesce
      // history replays and fetch the post-arbitration truth at the boundary.
      clearTimeout(renderStatus._refreshTimer);
      renderStatus._refreshTimer = setTimeout(async () => {
        try { renderStatus(await (await fetch(api("/api/status"))).json()); }
        catch (e) { addLine("sys", "Status delivery unconfirmed — reconnecting", { tick: true }); }
      }, 250);
    } else if (ev.t === "status") {
      // the engine-composed two-part status of record (disk map + engine
      // state, zero-model) — pane only, never the conversation
      closeCurrent();
      renderStatus(ev.status);
    } else if (ev.t === "sys") {
      closeCurrent();
      // a session that ended/slept emits sys, never turn_end — finalize the
      // live line here or its timer runs for the life of the tab and the next
      // turn appends into a dead turn's counter
      if (/session ended|asleep|could not start|CLI not found/i.test(ev.text || ""))
        endActivity(null);
      // tick-tagged housekeeping (drive continues, cadence commits) rides
      // the status pane; plain sys lines stay in the conversation
      addLine("sys", ev.text, ev.tick ? ev : undefined);
    }
    if (opts.onEvent) opts.onEvent(ev);
  }

  let epoch = null;
  async function poll() {
    for (;;) {
      try {
        const r = await fetch(api("/api/events?since=" + seq));
        const j = await r.json();
        // engine restarted/rebuilt: its seq counter reset, so our `since` is
        // stale - reset and replay history rather than go silent forever
        const ep = j.state && j.state.epoch;
        if (ep !== undefined && epoch !== null && ep !== epoch) {
          seq = 0; epoch = ep;
          const s = scrollEl(); if (s) s.textContent = "";
          resetActivity();   // the live line was just detached with the DOM
          addLine("sys", "— session reconnected —");
          if (!opts.skipHistory) await loadHistory();
          continue;
        }
        if (ep !== undefined) epoch = ep;
        if (j.gap) addLine("sys", "— some output scrolled past (buffer limit) —");
        (j.events || []).forEach(ev => { seq = Math.max(seq, ev.seq); handle(ev); });
        updateState(j.state);
        if (j.stamp && j.stamp !== stamp) { stamp = j.stamp; await loadMap(); }
      } catch (e) {
        await new Promise(res => setTimeout(res, 3000));
      }
    }
  }

  // a cheap idle repaint so the map also refreshes when the steward is quiet
  // or files change from outside this engine (not only on streamed events)
  async function stampPoll() {
    for (;;) {
      await new Promise(res => setTimeout(res, 3500));
      try {
        const r = await fetch(api("/api/state"));
        const j = await r.json();
        updateState(j);
        // A reader can observe projection publication between its writes.
        // Recheck reported inconsistency even if no later event changes stamp.
        if ((j.stamp && j.stamp !== stamp) || map?.refinement?.consistent === false) {
          if(j.stamp)stamp=j.stamp;
          await loadMap();
          await renderDeliverablesTile();
        }
      } catch (e) { /* the event poll handles backoff */ }
    }
  }

  function liveActivityWord(st) {
    if(!st) return '';
    const working=st.busy || st.working_bg || (st.alive && st.queued);
    const attention=st.attention_state || (_lastMap?.attention?.state) || '';
    return st.light==='red'?'Interrupted':working?'Working':st.open_question?'Needs your input':
      attention==='blocked'?'Blocked':attention==='needs_you'?'Needs your input':
      ['unknown','stale'].includes(attention)?'Activity unconfirmed':'Idle';
  }
  function syncCompactActivity(st) {
    if(!st)return;
    const value=liveActivityWord(st);
    const chip=$('.blk.status.latest [data-live-activity]');
    if(chip){chip.textContent=value;chip.title=value;}
    paintActionNeeded($('[data-openq]'));
    paintActionNeeded($('[data-status-action]'));
  }

  function updateState(st) {
    if (st) lastState = st;
    st = lastState;
    if (!st) return;
    if(_answerQuestionId && !(st.pending_questions||[]).some(q=>q.id===_answerQuestionId))_answerQuestionId=null;
    const busy = $("[data-busy]");
    if (busy) {
      busy.textContent = st.busy
        ? ((st.quiet_seconds || 0) >= 300
            ? "thinking " + Math.round(st.quiet_seconds / 60) + " min, no output - Stop turn interrupts"
            : (busySince ? "thinking " + Math.round((Date.now() - busySince) / 1000) + "s"
                         : "working..."))
        : "";
    }
    const spend = $("[data-spend]");
    if (spend) {
      const knownSessionUsd = value => typeof value === "number" && Number.isFinite(value) && value >= 0;
      const missingCostText = usage => {
        const count = Number.isInteger(usage.unpriced_turns) && usage.unpriced_turns > 0 ? usage.unpriced_turns : 0;
        const inflight = Number.isInteger(usage.unpriced_inflight) && usage.unpriced_inflight > 0;
        return count ? count.toLocaleString() + " unpriced turn" + (count === 1 ? "" : "s") + (inflight ? " + usage in progress" : "")
          : inflight ? "usage in progress; cost pending" : "unpriced usage";
      };
      const subscriptionCostText = (usage, reportedUsd, cli) => {
        const unpriced = Number.isInteger(usage.unpriced_turns) && usage.unpriced_turns > 0 ? usage.unpriced_turns : 0;
        const family = usage.billing_family || cli || "";
        const sub = usage.billing_mode === "subscription" || ((cli === "chatgpt" || cli === "grok") && unpriced > 0);
        if (!sub || unpriced <= 0) return null;
        const label = family === "mixed" ? "ChatGPT/Grok subscription"
          : family === "grok" || cli === "grok" ? "Grok subscription"
          : "ChatGPT subscription";
        const turns = " (" + unpriced.toLocaleString() + " turn" + (unpriced === 1 ? "" : "s") + ")";
        return (typeof reportedUsd === "number" && Number.isFinite(reportedUsd) && reportedUsd > 0)
          ? "$" + reportedUsd.toFixed(2) + " previously reported · " + label + turns
          : label + turns;
      };
      let sessionCostText = "cost unavailable" + (st.unpriced_turns > 0 || st.unpriced_inflight > 0 ? " · " + missingCostText(st) : "");
      if (typeof st.cost_text === "string" && st.cost_text) {
        sessionCostText = st.cost_text;
      } else {
        const sessionReported = knownSessionUsd(st.reported_spend_usd) ? st.reported_spend_usd
          : knownSessionUsd(st.spend_usd) ? st.spend_usd : null;
        const sessionSub = subscriptionCostText(st, sessionReported, st.cli);
        if (sessionSub) sessionCostText = sessionSub;
        else if (st.cost_status === "partial") {
          if (sessionReported !== null) sessionCostText = "cost incomplete · $" + sessionReported.toFixed(2) + " reported · " + missingCostText(st);
        } else if ((st.cost_status === "reported" || st.cost_status === undefined) && knownSessionUsd(st.spend_usd)) {
          sessionCostText = "$" + st.spend_usd.toFixed(2) + " reported";
        }
      }
      const recordedTokenText = (usage) => {
        const status = usage.token_status;
        const known = typeof usage.tokens === "number" && Number.isFinite(usage.tokens) && usage.tokens >= 0 &&
          status !== "unavailable" && (usage.tokens > 0 || status === "reported" ||
            (status === "partial" && usage.checkpoint_coverage && usage.checkpoint_coverage.reported_invocations > 0));
        return known ? Math.round(usage.tokens).toLocaleString() + " recorded tokens" +
          (status === "partial" ? " (partial)" : "") : "tokens unavailable";
      };
      const sessionTokensText = " · " + recordedTokenText(st);
      const effortUsage = !st.usage_persistence_error && st.usage_rollup && st.usage_rollup.total;
      let effortUsageText = "";
      if (effortUsage) {
        const reported = typeof effortUsage.reported_spend === "number" &&
          Number.isFinite(effortUsage.reported_spend) && effortUsage.reported_spend >= 0
          ? effortUsage.reported_spend : null;
        let effortCostText = "cost unavailable" + (effortUsage.unpriced_turns > 0 || effortUsage.unpriced_inflight > 0 ? " · " + missingCostText(effortUsage) : "");
        if (typeof effortUsage.cost_text === "string" && effortUsage.cost_text) {
          effortCostText = effortUsage.cost_text;
        } else {
          const effortSub = subscriptionCostText(effortUsage, reported, effortUsage.billing_family || st.cli);
          if (effortSub) effortCostText = effortSub;
          else if (effortUsage.cost_status !== "unavailable" && reported !== null) {
            if (effortUsage.cost_complete === true) effortCostText = "$" + reported.toFixed(2) + " reported";
            else if (reported > 0) effortCostText = "cost incomplete · $" + reported.toFixed(2) + " reported · " + missingCostText(effortUsage);
          }
        }
        effortUsageText = "effort sessions " + effortCostText + " · " + recordedTokenText(effortUsage);
        spend.title = "Session: " + sessionCostText + " · " + st.turns + " turns" + sessionTokensText +
          " · Effort total: " + effortCostText + " · " + recordedTokenText(effortUsage) +
          (effortUsage.usage_updated_at ? " · Last recorded " + effortUsage.usage_updated_at : " · Freshness unavailable") +
          (effortUsage.usage_source ? " · Source: " + effortUsage.usage_source : "");
      }
      // (codex-discipline Wave 2 S1) delegated jobs are a source of their own on
      // the line: shown only when rows exist, never as a zero; unknown usage is a count.
      const jobsUsage = !st.usage_persistence_error && st.usage_rollup && st.usage_rollup.jobs;
      const jobsText = (jobsUsage && Number.isInteger(jobsUsage.count) && jobsUsage.count > 0)
        ? " · " + jobsUsage.count + (jobsUsage.count === 1 ? " job " : " jobs ") + (jobsUsage.cost_text || "cost unavailable") +
          (jobsUsage.unknown > 0 ? " (" + jobsUsage.unknown + " unknown usage)" : "")
        : "";
      // (S2) sub-agents: their own clause, tokens only, never a zero.
      const kids = !st.usage_persistence_error && st.usage_rollup && st.usage_rollup.children;
      const kidsText = (kids && Number.isInteger(kids.count) && kids.count > 0)
        ? " · " + kids.count + (kids.count === 1 ? " sub-agent " : " sub-agents ") + recordedTokenText(kids) +
          (kids.unknown > 0 ? " (" + kids.unknown + " unknown usage)" : "")
        : "";
      // seats the effort's skills ran: their own clause, like jobs
      const seats = !st.usage_persistence_error && st.usage_rollup && st.usage_rollup.seats;
      const seatsText = (seats && Number.isInteger(seats.count) && seats.count > 0)
        ? " · " + seats.count + (seats.count === 1 ? " seat " : " seats ") + (seats.cost_text || "cost unavailable") +
          (seats.unknown > 0 ? " (" + seats.unknown + " unknown usage)" : "")
        : "";
      spend.textContent = (effortUsageText || "session " + sessionCostText + " · " + st.turns + " turns" + sessionTokensText) + jobsText + kidsText + seatsText +
        (st.usage_persistence_error ? " · not saved" : "") +
        (!st.alive ? " · " + (GENERAL ? "idle" : "steward asleep") + (st.queued ? " · " + st.queued + " held" : "") : "");
      if (!effortUsage) spend.title = "Session: " + sessionCostText + sessionTokensText;
      if (jobsText) spend.title += " · Delegated jobs" + jobsText.replace(/^ · /, ": ") + " · " + recordedTokenText(jobsUsage);
      if (kidsText) spend.title += " · Sub-agents" + kidsText.replace(/^ · /, ": ");
      if (seatsText) spend.title += " · Skill seats" + seatsText.replace(/^ · /, ": ") + " · " + recordedTokenText(seats);
      spend.title += " · Reported dollars are recorded charges, not an estimate. ChatGPT/Grok subscription turns have no per-turn dollar amount; token updates alone do not increase this subtotal.";
      if (st.usage_persistence_error) spend.title = "Usage totals could not be saved. These session counts are in memory and may be lost on restart.";
    }
    const wake = $("[data-wake]");
    if (wake) wake.textContent = st.alive ? "Sleep" : "Wake";
    const drive = $("[data-drive]");
    if (drive) {
      drive.textContent = st.drive ? "⏸ Pause" : "▶ Go";
      drive.classList.toggle("armed", !!st.drive);
      drive.title = st.drive
        ? "drive armed - continues without asking (" + st.auto_count + " so far)"
        : "arm drive: continue step after step until a decision is yours";
    }
    renderFiles(st.files || []);
    // the status window's light + plain-words state line
    const attention = (_lastMap && _lastMap.attention) || {};
    const attentionState = st.attention_state || attention.state || "";
    const attentionReason = st.attention_reason || attention.reason || "";
    const working = st.busy || st.working_bg || (st.alive && st.queued);
    syncCompactActivity(st);
    // Also support an already-running server from before the state contract repair.
    const color = st.light === "red" ? "red" : working ? "green"
      : (st.open_question || ["needs_you", "blocked"].includes(attentionState)) ? "orange" : "quiet";
    const light = $("[data-light]"), light2 = $("[data-light2]");
    if (light) light.className = "light " + color;
    if (light2) light2.className = "light " + color;
    const projectLight=$('[data-att]');
    if(projectLight){projectLight.className='dot light '+color;projectLight.title=
      color==='green'?'Working':color==='red'?'Interrupted':color==='orange'?'Needs your input':'Idle';}
    const stx = $("[data-statetext]");
    if (stx) {
      let txt;
      if (st.light === "red") txt = "stuck or broken — needs a look";
      else if (working) txt = "Working" +
        (attentionReason ? " — " + attentionReason : "");
      else if (!st.alive && st.queued) txt = st.queued +
        " held message(s) — waking the steward for delivery";
      else if (st.open_question) txt = "Waiting for your answer";
      else if (attentionState === "needs_you") txt = attentionReason || "Waiting for your answer";
      else if (attentionState === "blocked") txt = attentionReason || "Work is blocked";
      else if (attentionState === "unknown" || attentionState === "stale") txt = "Work status unconfirmed";
      else if (!st.alive) txt = "nothing running — asleep; your message wakes it";
      else txt = "Nothing running — ready";
      const details = [];
      const intr = $("[data-interrupt]");
      if (intr) intr.hidden = !(st.alive && st.busy);
      if (st.cli) details.push(st.cli);
      const policy = st.model_policy;
      if (policy && policy.model) details.push("requested " + policy.model + " / " + policy.effort);
      if (policy && policy.model_served) details.push("served " + policy.model_served + " · " +
        (policy.model_source === "provider-confirmed" ? "provider-confirmed" : "recorded by the CLI"));
      if (policy && policy.model_served && policy.model && !sameModel(policy.model, policy.model_served)) txt += " · model mismatch: served " + policy.model_served;
      if (st.pending_switch) details.push("switch to " + st.pending_switch + " at the next safe turn boundary");
      if (st.settings_error) txt += " · " + st.settings_error;
      stx.title = details.join(" · ");
      stx.title = [txt,stx.title].filter(Boolean).join(' · ');
      stx.textContent = color==='red'?'Interrupted':working?'Working':st.open_question?'Needs your input':
        attentionState==='blocked'?'Blocked':'Idle';
    }
    paintActionNeeded($("[data-openq]"));
    paintActionNeeded($("[data-status-action]"));
    const pm = $("[data-msgs]");
    if (pm) pm.textContent = "you: " + (st.john_msgs || 0) +
      " messages this session · ask “what's my overhead?” for the ease metric";
    document.body.dataset.alive = st.alive ? "1" : "";
  }

  // the served id is the requested one, or it plus a dated snapshot / build suffix; a sibling is another model
  function sameModel(requested, served) {
    requested = String(requested || ''); served = String(served || '');
    if (!requested || !served || served === requested) return true;
    return served.startsWith(requested) && /^-(?:\d[\d-]*|build.*)$/.test(served.slice(requested.length));
  }

  function openQuestionContext(questionId=null) {
    const host = $("[data-openq]") || $("[data-status-action]");
    if (!host) return;
    paintActionNeeded(host, questionId);
    host.classList.add("open");
  }

  /* ---------- files the steward touched ---------- */
  let _lastFiles = [], _filesSort = "date";
  function wireFileTools() {
    const s = $("[data-fsearch]");
    if (s && !s._wired) { s._wired = true; s.oninput = () => renderFiles(_lastFiles); }
    const sortBtns = Array.from(document.querySelectorAll("[data-fsort]"));
    sortBtns.forEach(b => {
      if (b._wired) return; b._wired = true;
      b.onclick = () => { _filesSort = b.getAttribute("data-fsort"); sortBtns.forEach(x => x.classList.toggle("on", x === b)); renderFiles(_lastFiles); };
    });
  }
  // a produced file opens rendered in a new window when it lies inside this effort
  function openProducedFile(f) {
    const root = (_lastMap && _lastMap.dir) || "";
    const norm = (x) => String(x || "").replace(/\\/g, "/");
    const fn = norm(f), rn = norm(root).replace(/\/$/, "");
    if (rn && fn.toLowerCase().indexOf(rn.toLowerCase() + "/") === 0) {
      const rel = fn.slice(rn.length + 1);
      if (/\.(md|txt|csv|json|log)$/i.test(rel)) { window.open("/report?dir=" + encodeURIComponent(DIR) + "&path=" + encodeURIComponent(rel)); return; }
      window.open("/api/steward/deliverable-file?pid=" + encodeURIComponent(window.STEWARD_PID || "") + "&dir=" + encodeURIComponent(DIR) +
        "&path=" + encodeURIComponent(rel) + (/\.(docx|pptx|xlsx)$/i.test(rel) ? "&view=1" : "") +
        (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : ""));
      return;
    }
    post("/api/open", { path: f });   // outside the effort: the app opens it, said in the row
  }
  function renderFiles(files) {
    wireFileTools();
    const list = $("[data-flist]");
    if (!list) return;
    const cnt = $("[data-filecount]");
    if (cnt) cnt.textContent = "(" + files.length + ")";
    const head = $("[data-filestoggle]"), sect = $("[data-filesect]");
    if (head && sect && !head._wired) {
      head._wired = true;
      try {
        if (localStorage.getItem("steward_files_open") === "1")
          sect.classList.remove("folded");
      } catch (e) { /* no-op */ }
      head.onclick = () => {
        sect.classList.toggle("folded");
        try {
          localStorage.setItem("steward_files_open",
            sect.classList.contains("folded") ? "0" : "1");
        } catch (e) { /* no-op */ }
      };
    }
    // (2026-09-05, John) files are searchable, sortable (name / type / date order
    // as produced) and OPEN IN A NEW WINDOW rendered; "app" opens them on this
    // computer as before.
    _lastFiles = files.slice();
    const q = (($("[data-fsearch]") || {}).value || "").trim().toLowerCase();
    const sort = _filesSort;
    let rows = files.map((f, i) => ({ f, i, name: f.split(/[\\/]/).pop() }));
    if (q) rows = rows.filter(r => r.name.toLowerCase().indexOf(q) >= 0);
    if (sort === "name") rows.sort((a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    else if (sort === "type") rows.sort((a, b) => (a.name.split(".").pop() || "").toLowerCase().localeCompare((b.name.split(".").pop() || "").toLowerCase()) || a.name.toLowerCase().localeCompare(b.name.toLowerCase()));
    else rows.sort((a, b) => b.i - a.i);   // "date": newest produced first
    list.textContent = "";
    rows.forEach(({ f, name }) => {
      const row = el("div", "frow");
      const a = document.createElement("a");
      a.className = "fname"; a.textContent = name; a.href = "#";
      a.onclick = (ev) => { ev.preventDefault(); openProducedFile(f); };
      row.appendChild(a);
      const btn = el("button", "", "app");
      btn.title = "open on this computer";
      btn.onclick = () => post("/api/open", { path: f });
      row.appendChild(btn);
      list.appendChild(row);
    });
    if (!rows.length) list.appendChild(el("div", "frow", files.length ? "nothing matches" : "(none yet)"));
  }

  /* ---------- work-product overlay (tile on the plan rail) ---------- */
  function closeWorkMap() {
    const ov = $("[data-wpmap]");
    if (ov) ov.hidden = true;
  }
  function openWorkMap() {
    if(_lastMap)paintWorkMap(_lastMap);
    const ov = $("[data-wpmap]");
    if (ov) ov.hidden = false;
  }
  let _plates = [];
  let _plateId = "";
  function paintWorkMap(map) {
    const organization=navModel(map,_deliv.items);
    if(organization) {
      const sum=$('[data-wpsum]'),title=$('[data-wptitle]'),goal=$('[data-wpgoal]'),hint=$('[data-wphint]'),body=$('[data-wpbody]');
      if(sum)sum.textContent=organization.roots.length+' groups — click to open';
      if(title)title.textContent='Work map';
      if(goal)goal.textContent=map.goal_brief||'';
      if(hint)hint.textContent='The same organization as Plan and Deliverables. Current files open directly.';
      if(body){body.textContent='';renderNavigation(body,map,_deliv.items,'work-map');}
      const atlas=$('[data-wpatlas]');if(atlas)atlas.hidden=true;
      return;
    }
    const plate = (map && map.plate) || null;
    _plates = plate ? [plate] : [];
    _plateId = plate ? (plate.deliverableId || plate.title || "") : "";
    const sum = $("[data-wpsum]");
    if (sum) sum.textContent = plate
      ? ((plate.title || "plate") + " — click to open")
      : "no plate yet";
    const title = $("[data-wptitle]");
    if (title) title.textContent = (plate && plate.title) || "No plate yet";
    const gline = $("[data-wpgoal]");
    if (gline) gline.textContent = (plate && plate.subtitle) || "";
    const hint = $("[data-wphint]");
    if (hint) hint.textContent = plate
      ? "Parts of the thing you will open. Hollow = a reserved hole, not a chore. Click a part."
      : "No authored plate for this effort yet.";
    const body = $("[data-wpbody]");
    if (!body || !globalThis.DeliverablePlate) return;
    const atlas = $("[data-wpatlas]");
    if (atlas) atlas.hidden = true;
    DeliverablePlate.paintPlate(body, plate);
  }
  function wireWorkMap() {
    const tile = $("[data-wptile]");
    const ov = $("[data-wpmap]");
    if (tile) tile.onclick = () => openWorkMap();
    const x = $("[data-wpclose]");
    if (x) x.onclick = () => closeWorkMap();
    if (ov) ov.addEventListener("click", (ev) => {
      if (ev.target === ov) closeWorkMap();
    });
    document.addEventListener("keydown", (ev) => {
      if (ev.key === "Escape") closeWorkMap();
    });
  }

  /* ---------- the map ---------- */
  async function loadMap() {
    const r = await fetch(api("/api/map"));
    map = await r.json();
    // The existing managed read route exposes event-derived navigation without a server restart.
    const navigation=(map.refinement && map.refinement.navigation) || {};
    (map.steps || []).forEach(s=>{if(navigation[s.id])s.navigation=navigation[s.id];});
    stamp = map.stamp;
    if (map.steward && !opts._labelSet) {
      opts.stewardLabel = map.steward.toUpperCase();
      opts._labelSet = true;
    }
    document.title = (map.attention.state === "needs_you" ? "⚑ " :
                      map.attention.state === "working" ? "▶ " : "") +
                     map.name + " — steward";
    if (opts.renderMap) { opts.renderMap(map); return; }
    // goal tile (one sentence; expands to the full bold-led description)
    const gb = $("[data-goalbrief]");
    if (gb) gb.textContent = _statusLine || map.goal_brief || "(no goal recorded)";
    const gf = $("[data-goalfull]");
    if (gf) renderRich(gf, map.goal_md || "(no goal recorded)");
    paintKickoff(gb);
    const gh = $("[data-goalhist]");
    if (gh && map.history) {
      const d = map.history.days || 0;
      let h = "**Running** " + d + (d === 1 ? " day" : " days") +
        (map.history.started ? " (record since " + map.history.started + ")" : "") +
        " · " + map.steps_done + " of " + map.steps_total + " steps done" +
        " · last talked " + map.freshness.talked;
      if (map.history.history_md) h += "\n\n" + map.history.history_md;
      renderRich(gh, h);
    }
    const latest = $("[data-latest]");
    if (latest) {
      const line = (map.heartbeat.why_next || map.heartbeat.next_recommended || "")
        .split("\n").filter(Boolean)[0] || "(no heartbeat recorded)";
      latest.textContent = "most recent from the record (" +
        map.freshness.heartbeat + "): " + line.replace(/\*\*/g, "").slice(0, 220);
    }
    const goal = $("[data-goal]");
    if (goal) goal.textContent = map.goal || "(no goal recorded)";
    const prog = $("[data-progress]");
    if (prog) prog.textContent = map.steps_done + " of " + map.steps_total + " steps done";
    _lastMap = map;
    paintStepsList(map);
    try { paintWorkMap(map); } catch (e) { /* overlay optional */ }
    const wait = $("[data-wait]");
    if (wait) wait.textContent = map.heartbeat.human_wait || "(nothing)";
    const grass = $("[data-grass]");
    if (grass) {
      grass.textContent = "";
      (map.grasscatch.length ? map.grasscatch : []).forEach(g =>
        grass.appendChild(el("li", "", typeof g === "string" ? g : JSON.stringify(g))));
      if (!map.grasscatch.length) grass.appendChild(el("li", "", "(empty)"));
    }
    const fresh = $("[data-fresh]");
    if (fresh) fresh.textContent = "talked " + map.freshness.talked +
      " · plan " + map.freshness.plan + " · heartbeat " + map.freshness.heartbeat;
    const gaps = $("[data-gaps]");
    if (gaps) gaps.textContent = (map.gaps || []).join(" · ");
    const att = $("[data-att]");
    if (att && !lastState) { att.className = "dot " + (map.attention.state || "unknown");
               att.title = map.attention.state +
                 (map.attention.reason ? " - " + map.attention.reason : ""); }
    const name = $("[data-name]");
    if (name) name.textContent = map.name;
    if(lastState)updateState(lastState);
    if (opts.afterMap) opts.afterMap(map);
  }

  /* ---------- history ---------- */
  async function loadHistory() {
    const r = await fetch(api("/api/history"));
    const j = await r.json();
    (j.turns || []).forEach(t => addBlock(
      t.role === "john" ? "john" : "steward",
      t.role === "john" ? (opts.johnLabel || "JOHN") : (opts.stewardLabel || "ECGBERHT"),
      t.text, "hist"));
    if (j.turns && j.turns.length)
      addLine("divider", "—— live from here ——");
    pin(scrollEl(), true);
  }

  /* ---------- composer + dictation ---------- */
  async function sendSay(text, questionId) {
    try {
      const r = await post("/api/say", { text, refinement_context: _refinementContext, question_id: questionId || null });
      const j = await r.json();
      if (j.ok) {
        _refinementContext = null; _answerQuestionId = null;
        const ta = $("[data-say]");
        if (ta) ta.placeholder = "";
      } else {
        _answerQuestionId = null;
        addLine("sys", "not delivered: " + (j.error || "?") + " - your text is back in the box");
      }
      return j;
    } catch (e) {
      _answerQuestionId = null;
      addLine("sys", "not delivered (network) - your text is back in the box");
      return {ok: false};
    }
  }
  function wireComposer() {
    const ta = $("[data-say]");
    const send = $("[data-send]");
    if (!ta) return;
    const grow = () => { ta.style.height = "auto";
                         ta.style.height = Math.min(ta.scrollHeight + 2, innerHeight * 0.4) + "px"; };
    ta.addEventListener("input", grow);
    const submit = async () => {
      let text = ta.value.trim();
      if (!text) return;
      // dictation-friendly grasscatch: "later: ..." parks it without ceremony
      const later = text.match(/^(later|grasscatcher?)[:,]\s*(.+)/is);
      if (later) text = "Grasscatch this (park it on the Strip with a reason, " +
                        "then carry on with the step in hand): " + later[2];
      const keep = ta.value;
      ta.value = ""; grow();
      const j = await sendSay(text, _answerQuestionId);
      if (!j.ok) { ta.value = keep; grow(); }
    };
    if (send) send.onclick = submit;
    // (codex-discipline-2026-09-15 Wave 1.2) Send is disabled in the markup
    // and enabled only once its handler exists: a click in the load window
    // used to produce neither a POST nor a record.
    if (send) send.disabled = false;
    ta.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" || e.isComposing) return;
      // (2026-09-04, John) Enter sends, the same as the Send button; Shift+Enter
      // keeps a newline. Dictation (Win+H) never presses Enter, so the button
      // stays the way to send dictated text.
      if (e.shiftKey) return;
      e.preventDefault(); submit();
    });
    // Dictation is Win+H (2026-08-25, jrnl 0088): the in-page Web Speech mic
    // was choppy and never auto-punctuated, so it is GONE — the textarea
    // stays a clean Win+H target (never locked, text never lost).
  }

  function wireChrome() {
    const wake = $("[data-wake]");
    if (wake) wake.onclick = async () => {
      const alive = document.body.dataset.alive === "1";
      await post("/api/engine", { action: alive ? "stop" : "wake" });
    };
    const intr = $("[data-interrupt]");
    if (intr) intr.onclick = async () => {
      // Wave 1.3: Stop turn - ends the running turn (outcome recorded as
      // uncertain, partial work kept); the queue and the thread survive.
      await post("/api/engine", { action: "interrupt", reason: "stopped by John" });
    };
    const drive = $("[data-drive]");
    if (drive) drive.onclick = async () => {
      const on = lastState && lastState.drive;
      await post("/api/engine", { action: on ? "drive_off" : "drive_on" });
      if (!on && !(lastState && lastState.alive)) await post("/api/say", { text: "go" });
    };
    const mini = $("[data-min]");
    const app = $(".app");
    if (mini) mini.onclick = () => {
      if (EMBED) parent.postMessage({ proto: "min" }, "*");  // inside the cockpit
      else location.href = "/";                              // standalone: dashboard (not the High Seat overlay)
    };
    const railT = $("[data-railtoggle]");
    if (railT && app) railT.onclick = () => app.classList.toggle("railhide");
    const goalbar = $("[data-goalbar]");
    if (goalbar) goalbar.onclick = () => goalbar.classList.toggle("open");
    const paneT = $("[data-panetoggle]");
    const pane = $("[data-statuspane]");
    if (paneT && pane) paneT.onclick = () => pane.classList.toggle("shut");
    const bone = $("[data-boneyard]");
    if (bone) bone.onclick = async () => {
      if (!confirm("Boneyard this effort? It is archived (not deleted) and can be restored from the seal's boneyard.")) return;
      const r = await post("/api/boneyard_move", {});
      const j = await r.json();
      if (j.ok) location.href = "/";
      else alert(j.error || "could not boneyard it");
    };
    const themeBtn = $("[data-theme-toggle]");
    if (themeBtn) themeBtn.onclick = () => Proto.toggleTheme();
    const catchIn = $("[data-catch]");
    if (catchIn) catchIn.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && catchIn.value.trim()) {
        post("/api/say", { text: "Grasscatch this (park it on the Strip, then carry on): " + catchIn.value.trim() });
        catchIn.value = "";
      }
    });
  }

  function applyTheme() {
    let t = "slate";
    try { t = localStorage.getItem("protoTheme") || "slate"; } catch (e) {}
    document.body.dataset.theme = t;
  }
  function toggleTheme() {
    const next = document.body.dataset.theme === "command" ? "slate" : "command";
    try { localStorage.setItem("protoTheme", next); } catch (e) {}
    document.body.dataset.theme = next;
  }

  async function init(o) {
    opts = o || {};
    if (opts.stewardLabel) opts._labelSet = true;
    applyTheme();
    try { await loadMap(); } catch (e) {
      const p = $("[data-progress]");
      if (p) p.textContent = "map failed: " + ((e && e.message) || "could not load");
    }
    if (!opts.skipHistory) {
      try { await loadHistory(); } catch (e) { /* no-op */ }
    }
    if (opts.statusPane) {
      // paint the pane's status of record immediately (composed fresh,
      // zero-model) so it never opens empty waiting for the next cadence
      try { renderStatus(await (await fetch(api("/api/status"))).json()); }
      catch (e) {}
    }
    // deliverables surface on open (tile + goal/map links) — John's ask 2026-08-25
    try { renderDeliverablesTile(); } catch (e) {}
    wireComposer();
    wireChrome();
    try { wireWorkMap(); } catch (e) {}
    poll();
    stampPoll();
    setInterval(() => updateState(null), 1000); // busy clock repaint
  }

  window.addEventListener("anchor-notebooks-changed", () => {
    renderDeliverablesTile().catch(() => {});
  });

  return { init, addLine, applyTheme, toggleTheme,
           get map() { return map; }, get dir() { return DIR; } };
})();
