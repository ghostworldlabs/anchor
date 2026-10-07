/* steward-proto shared client. Safe rendering: model text goes through
   textContent-based builders only - no innerHTML anywhere.
   All API calls carry the effort's dir (?dir=<rel>) so one server hosts
   several steward efforts at once. */
"use strict";

const Proto = (() => {
  const PARAMS = new URLSearchParams(location.search);
  const DIR = PARAMS.get("dir") || "";
  const STEP = PARAMS.get("step") || "";   // W5 (2026-09-28): Resume from the High Seat lands on this step
  let _stepShown = false;
  const GENERAL = PARAMS.get("general") === "1";
  const TERM = PARAMS.get("term") || "";
  const EMBED = PARAMS.get("embed") === "1";
  // the Cave of Wonders' open tile shows THIS view (2026-10-02, his word: "if I had both open I'd be able to see
  // exactly the same information flowing into the dialog ... and the status bar should be doing the same thing"):
  // one renderer, one engine stream. The tile hears this view through a bridge scoped to its instance and origin.
  const TALK = EMBED && PARAMS.get("view") === "talk";
  const TILE = EMBED && (PARAMS.get("view") === "tile" || TALK);
  const INST = PARAMS.get("inst") || "";
  function tileSay(kind, data) {
    if (!TILE || window.parent === window) return;
    try { window.parent.postMessage(Object.assign({ proto: "anchor-tile", inst: INST, kind: kind }, data || {}), location.origin); } catch (e) {}
  }
  // a tile view the Cave preloads hidden for an Active card (2026-10-06, his word: "keep the memory open ... so that it
  // loads instantly when I click on the tile"): parked, it holds no long-poll (the browser's few connections per host
  // stay free for the page); shown, it catches up from its seq at once and lays itself out
  let parked = TILE && PARAMS.get("parked") === "1", _pollAbort = null, _unpark = null;
  function setParked(p) {
    parked = !!p;
    if (parked) { try { if (_pollAbort) _pollAbort.abort(); } catch (e) {} return; }
    const go = _unpark; _unpark = null; if (go) go();
    { const d = scrollEl(); pin(d, !!d && d._follow !== false); } pin(paneEl(), true);   // a hidden frame had no size to scroll by; the dialogue keeps his place
    const ta = document.querySelector("[data-say]");
    if (ta && ta.value) { ta.style.height = "auto"; ta.style.height = Math.min(ta.scrollHeight + 2, innerHeight * 0.4) + "px"; }
  }
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
  // W0 (High Seat, 2026-09-26): a step's calendar date, ISO in the record, "Oct 8" on the page
  function fmtDue(iso) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(iso || ""));
    if (!m) return String(iso || "");
    return new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])).toLocaleDateString("en-US", {month: "short", day: "numeric", timeZone: "UTC"});
  }
  // the wait on John, from structured facts only: a product awaiting his review or blocked, a step the
  // steward set to waiting or blocked; never a text match
  function stepWaitsOnJohn(st) {
    if (!st) return "";
    const r = st.refinement;
    if (r && r.phase === "awaiting_review") return "awaiting your review";
    if (r && r.phase === "blocked") return "blocked";
    if (st.status === "blocked") return "blocked";
    if (st.status === "waiting") return hasWaitingOn(st.waiting_on) ? oneLine(String(st.waiting_on), 90) : "waiting";
    return "";
  }
  function stepNeedsAttention(st) { return !!stepWaitsOnJohn(st); }
  // the one current step, named by the server (map.now_step_id from _focused_step); never a guess on the page
  function isNow(st, map) { return !!(map && map.now_step_id && st && st.id === map.now_step_id); }
  function planMarkInfo(st, map) {
    if (stepDone(st)) return {glyph: "✓", cls: "done", row: "done"};
    if (stepNeedsAttention(st)) return {glyph: "⚑", cls: "flag", row: "waiting"};
    if (isNow(st, map)) return {glyph: "●", cls: "now", row: "active"};
    return {glyph: "", cls: "todo", row: st.status === "active" ? "active" : "planned"};
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
    // bullets: the context sentences, the recommendation as the first button with its why, the alternatives
    const bullets = el("ul", "action-bullets");
    (Array.isArray(q.stake) ? q.stake : (q.stake ? [q.stake] : [])).slice(0, 3).forEach(sentence => bullets.appendChild(el("li", "action-stake", oneLine(sentence, 220))));
    if (!q.recommendation) bullets.appendChild(el("li", "action-rec dim", "no recommendation given"));
    if (q.recommendation) {
      const row = el("li", "action-rec");
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
      row.appendChild(el("span", "action-rectext", " " + oneLine(q.recommendation, 220) + (q.why ? " \u2014 " + oneLine(q.why, 160) : "")));
      bullets.appendChild(row);
    }
    if (q.authorizes) bullets.appendChild(el("li", "action-auth", "Authorizes: " + oneLine(q.authorizes, 160)));
    if (q.decide_by) bullets.appendChild(el("li", "action-auth", "Decide by: " + oneLine(q.decide_by, 80)));
    if (q.reversible === true && q.undo) {
      const secs = 4 * 3600;      // the server's silence window
      const at = typeof q.asked_at === "number" ? new Date((q.asked_at + secs) * 1000) : null;
      const when = at ? at.toLocaleTimeString([], {hour: "2-digit", minute: "2-digit"}) + (at.toDateString() === new Date().toDateString() ? "" : " " + at.toLocaleDateString()) : "after " + Math.round(secs / 3600) + " hours";
      bullets.appendChild(el("li", "action-auth", "Reversible \u00b7 proceeds on the recommendation at " + when + " if unanswered \u00b7 undo: " + oneLine(q.undo, 120)));
    } else if (q.reversible === false) {
      bullets.appendChild(el("li", "action-auth", "Not reversible \u00b7 waits for you"));
    }
    (q.alternatives || []).slice(0, 3).forEach(a => {
      const row = el("li", "action-alts");
      const choose = el("button", "action-alt", "Choose");
      choose.onclick = async (ev) => {
        ev.stopPropagation();
        if (q.id && !pending().some(item => item.id === q.id)) return gone(choose);
        choose.disabled = true;
        const tile = host.closest("[data-openq],[data-status-action]");
        const result = await sendSay("Alternative: " + a, q.id || null);
        if (result && result.ok) { if (tile) tile.classList.remove("open"); }
        else choose.disabled = false;
      };
      row.appendChild(choose);
      row.appendChild(el("span", "action-rectext", " " + oneLine(a, 120)));
      bullets.appendChild(row);
    });
    host.appendChild(bullets);
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
      decided.slice().reverse().forEach(h => {
        const p = el("p", "sdmeta", oneLine(h.question, 90) + " \u2192 " + oneLine(h.answer, 60) + (h.status === "proceeded_on_silence" ? " \u00b7 proceeded on silence" : ""));
        if (h.status === "proceeded_on_silence" && h.undo) {
          const undo = el("button", "action-alt", "Undo");
          undo.onclick = async (ev) => {
            ev.stopPropagation(); undo.disabled = true;
            const result = await sendSay("Undo the decision that proceeded on silence: " + h.undo, null);
            if (!(result && result.ok)) undo.disabled = false;
          };
          p.appendChild(document.createTextNode(" ")); p.appendChild(undo);
        }
        d.appendChild(p);
      });
      host.appendChild(d);
    }
    const others = el("div", "question-others");
    fillOtherQuestions(others, q);
    host.appendChild(others);
  }
  function fillOtherQuestions(box, q) {
    // the other pending questions: refreshed on their own when one arrives or resolves, so the open question's
    // expanded context, loaded exchange and focused button stay as they are (ChatGPT review, item 1 round 2)
    box.textContent = "";
    ((lastState && lastState.pending_questions) || []).filter(item => item.id !== q.id).forEach(item => {
      const b = el("button", "question-other", item.question);
      b.onclick = (ev) => { ev.stopPropagation(); paintActionNeeded(box.closest("[data-openq],[data-status-action]"), item.id); };
      box.appendChild(b);
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
          if (m && m[1]) briefEl.textContent = m[1].trim();
        }
      } else if (j.state === "open" && j.open_draft && j.open_draft.applied === false) {
        box.classList.add("draft");
        if (briefEl && j.open_draft.goal) briefEl.textContent = "draft, not applied — " + j.open_draft.goal;
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
    if (s && s._followWired) return s._follow;   // the dialogue: John's own scrolling decides (wireFollow)
    return s.scrollHeight - s.scrollTop - s.clientHeight < 120;
  }
  function pin(s, force) {
    if (s && (force || atBottom(s))) s.scrollTop = s.scrollHeight;
  }
  // 2026-10-07 (John, evidence E6: a cockpit opened somewhere in the middle): the dialogue opens at the newest
  // message and stays there while content arrives or renders (markdown, images, a late layout) - until John scrolls
  // up. Only a real scroll changes `follow`; growth of the content fires no scroll event, so it never breaks it.
  function wireFollow(s) {
    if (!s || s._followWired) return;
    s._followWired = true;
    s._follow = true;
    // following stops on ANY upward move of his and resumes only when he reaches the very bottom again (ChatGPT
    // review: a 120 px "near the bottom" band re-armed it after a small upward scroll, then yanked him down)
    let lastTop = s.scrollTop;
    const stick = () => { if (s._follow) { s.scrollTop = s.scrollHeight; lastTop = s.scrollTop; } };
    s.addEventListener("scroll", () => {
      const gap = s.scrollHeight - s.scrollTop - s.clientHeight;
      if (gap < 4) s._follow = true;                       // at the bottom (also a clamp after content shrank)
      else if (s.scrollTop < lastTop - 1) s._follow = false;
      lastTop = s.scrollTop;
    }, { passive: true });
    s.addEventListener("wheel", (e) => { if (e.deltaY < 0) s._follow = false; }, { passive: true });
    s.addEventListener("load", stick, true);                     // an image or frame inside finished loading
    if (window.ResizeObserver) {
      const ro = new ResizeObserver(stick);
      ro.observe(s);
      Array.from(s.children).forEach(c => ro.observe(c));
      if (window.MutationObserver) new MutationObserver((muts) => {
        muts.forEach(m => m.addedNodes.forEach(n => { if (n.nodeType === 1 && n.parentElement === s) ro.observe(n); }));
        stick();
      }).observe(s, { childList: true, subtree: true, characterData: true });
    }
    stick();
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
      tileSay("turn", { who: "steward", text: String(currentBlock._raw || body.textContent || "").slice(-600) });
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
  // Do now under the lead: the open decision, then the acts the deliverables read serves (Review, Open, Next)
  function paintNextSteps(host) {
    // 2026-10-07: a repaint keeps John's place - the focused link and the scroll position survive it
    const focusKey = host.contains(document.activeElement) && document.activeElement.dataset.navFocus;
    const scroller = host.closest(".body") || host;
    const priorScroll = scroller.scrollTop;
    try { return _paintNextSteps(host); }
    finally { scroller.scrollTop = priorScroll; restoreNavFocus(focusKey); }
  }
  function companionLinks(a) {
    // the other formats of the same product: one decision, the extra formats as small links on its row
    const box = el("div", "navcompanions");
    box.appendChild(el("span", "sdmeta", "also "));
    a.companions.forEach((c, i) => {
      const ext = String(c.path || c.route || "").split("?")[0].split(".").pop().toUpperCase();
      const row = delivRow({...(c.item || {}), what: ext || "other format", path: c.path, route: c.route, openable: true, step: a.step});
      const link = row.querySelector("a");
      if (!link) return;
      link.textContent = ext || "other format";
      link.dataset.navFocus = "next:companion:" + (c.path || c.route);
      if (i) box.appendChild(document.createTextNode(" · "));
      box.appendChild(link);
    });
    return box;
  }
  function questionSig() {
    // everything the question row shows: every pending question (its others are buttons), the open one, the decisions
    const st = lastState || {};
    return JSON.stringify([st.pending_questions || [], st.question_context || null, st.open_question || "",
                           (st.decision_history || []).length]);
  }
  function openQuestionSig() {
    // the open question itself - a change here repaints the row; the OTHER questions refresh on their own
    const st = lastState || {};
    return JSON.stringify([currentQuestion(), st.question_context || null, st.open_question || "",
                           (st.decision_history || []).length]);
  }
  function _paintNextSteps(host) {
    // 2026-10-07 (ChatGPT review of item 1): KEYED rows. A row is rebuilt only when its own content changed; every
    // other row keeps its node - so its focus, an expanded disclosure, and a click that spans a poll all survive.
    const rows = host._rows || (host._rows = new Map());
    const want = [], used = new Set(), replaced = [];
    const keep = (key, sig, build, after) => {
      let k = key, n = 1;
      while (used.has(k)) k = key + "#" + (++n);   // two rows with one key stay two rows
      used.add(k); key = k;
      let r = rows.get(key);
      if (!r || r.sig !== sig) {
        const old = r ? r.node : null;
        const node = r && r.reuse ? r.node : build();
        if (old && old !== node) replaced.push([old, node]);
        r = {sig, node, reuse: r ? r.reuse : false};
        rows.set(key, r);
        if (after) after(node);
      }
      want.push(r.node);
      return r.node;
    };
    const q = currentQuestion();
    // the question row keeps its node and its open state; a changed question set repaints inside it
    const ask = keep("ask", openQuestionSig(), () => { const n = el("div", "action-needed"); n.dataset.statusAction = "1"; return n; },
         (n) => { delete n.dataset.questionId; paintActionNeeded(n); n._othersSig = questionSig(); });
    rows.get("ask").reuse = true;
    if (ask._othersSig !== questionSig()) {            // another question arrived or resolved: only the list moves
      ask._othersSig = questionSig();
      const box = ask.querySelector(".question-others");
      const shown = ((lastState && lastState.pending_questions) || []).find(x => (x.id || x.question) === ask.dataset.questionId)
        || currentQuestion();
      if (box && shown) fillOtherQuestions(box, shown);
      else { delete ask.dataset.questionId; paintActionNeeded(ask); }
    }
    const acts = _deliv.acts || [];
    if (_deliv.warning) keep("warning", _deliv.warning, () => el("div", "navempty", _deliv.warning));   // the current item, honestly
    acts.forEach(a => {
      keep("act:" + a.act + ":" + (a.path || a.label || ""), JSON.stringify(a), () => {
        const row = el("div", "navact navact-" + a.act.toLowerCase());
        row.appendChild(el("span", "navactkind", a.act));
        if (a.item) row.appendChild(navFile(a.item.managed && a.companions && a.companions.length
        ? {...a.item, _alsoAccept: a.companions.map(c => c.item).filter(c => c && c.managed && c.presentation_id === a.item.presentation_id)}
        : a.item, "next:act"));
        else if (a.path) row.appendChild(navFile({what: a.label, path: a.path, openable: true, step: a.step}, "next:act"));
        else row.appendChild(el("span", "navactlabel", a.label));
        if (a.companions && a.companions.length) row.appendChild(companionLinks(a));
        return row;
      });
    });
    const waits = (q && q.question ? 1 : 0) + acts.length;
    if (!waits) keep("empty", "", () => el("div", "navempty", "Nothing waits on you."));
    // W1 of the steward revision (2026-09-28): the next-in-the-plan horizon is computed ONCE on the server
    // (steward_campaign.next_in_plan: the declared focus, then what follows it; never a guess from the first
    // active step) and read here from the map — the card on the High Seat reads the same list. No focus: nothing.
    const plan = (_lastMap && Array.isArray(_lastMap.next_in_plan)) ? _lastMap.next_in_plan : [];
    if (plan.length) {
      keep("plan:eyebrow", "", () => el("div", "naveyebrow", "Next in the plan"));
      plan.forEach((st, i) => {
        const text = ((st.navigation && st.navigation.label) || st.name) + (st.due ? " · due " + fmtDue(st.due) : "");
        keep("plan:" + i, text, () => el("div", "navactlabel", text));
      });
    }
    // a changed row takes its old row's place; rows that are gone leave first; then only out-of-order rows move (a
    // moved node loses its focus, so an unchanged row is never moved because a neighbour changed)
    replaced.forEach(([old, node]) => { if (old.parentNode === host) host.replaceChild(node, old); });
    const wanted = new Set(want);
    Array.from(host.children).forEach(c => { if (!wanted.has(c)) host.removeChild(c); });
    want.forEach((node, i) => { if (host.children[i] !== node) host.insertBefore(node, host.children[i] || null); });
    const live = new Set(want);
    Array.from(rows.keys()).forEach(k => { if (!live.has(rows.get(k).node)) rows.delete(k); });
    return waits;
  }
  function renderNextStepsTile() {
    const s = $("[data-delivmount]");
    if (!s) return;
    let tile = s.querySelector(".blk.next");
    if (!tile) {
      tile = el("div", "blk steward next folded");
      const who = el("div", "who");
      who.style.cursor = "pointer";
      who.onclick = () => tile.classList.toggle("folded");
      tile.appendChild(who);
      tile.appendChild(el("div", "body"));
      s.appendChild(tile);
    }
    // 2026-10-07: repaint only when what the tile shows changed. It was rebuilt from scratch every second (the
    // 1 s busy-clock tick), which re-created icons, swallowed clicks that spanned a rebuild, and reset focus.
    const sig = JSON.stringify([questionSig(),
      _deliv.acts || [], _deliv.warning || "", (_lastMap && _lastMap.next_in_plan) || []]);
    if (tile.dataset.sig === sig) return;
    tile.dataset.sig = sig;
    const n = paintNextSteps(tile.querySelector(".body"));
    const act = (_deliv.acts || []).find(a => a && (a.label || (a.item && a.item.what)));
    const actLabel = act ? shortWhat(act.item || {what: act.label}) : "";
    tile.querySelector(".who").textContent = "NEXT STEPS" + (n ? " \u00b7 " + n + " for you" : " \u00b7 nothing waits on you") + (actLabel ? " \u2014 " + actLabel : "");
  }
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
    else if (stat.from_record) who.appendChild(el("span", "stale",   // W3c (2026-10-01): the record now, the last run named by its date - the tile's and the Desk's clause
      stat.last_run_at ? " · the record now; the last run " + String(stat.last_run_at).slice(-16) : " · the record now; no run yet"));
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
    const skillRow = text => {
      const im = run && (run.kind === "skill" || run.kind === "commissioned") && window.SkillIcons && window.SkillIcons.img(run.skill || run.label || "", 14);
      if (!im) return text;
      const span = el("span", "");
      span.appendChild(im);
      span.appendChild(document.createTextNode(text));
      return span;
    };
    const rows = [
      ["Summary", factValue("Summary", sliceLine || oneLine(goal) || "—")],
      ["Effort", factValue("Effort", stat.effort || "—")],
      ["Doing", skillRow(factValue("Doing", doingLine || (stat.stale ? "Idle" : "—")))],
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
    body.appendChild(compact);
    if (p.goal_reread === false)
      body.appendChild(el("div", "splan sflag", "goal not re-read since last close"));
    b.appendChild(body);
    // (2026-09-05, John) the NEWEST status is always prominent: it carries
    // .latest, older blocks above it are folded to their time line, and the
    // pane always brings the newest into view (a status pane is for now,
    // not for reading history — history stays one click away).
    s.querySelectorAll(".blk.status.latest").forEach(o => o.classList.remove("latest"));   // it stays below, folded to its time line
    b.classList.add("latest");
    s.insertBefore(b,s.firstChild);
    syncCompactActivity(lastState);
    s.scrollTop=0;
    // the window's header carries the time of the last update (idle projects
    // show their LAST update, stamped, not a fresh blank)
    const stamp = $("[data-statusstamp]");
    if (stamp) stamp.textContent = "last update " + hhmm + (stat.stale ? " · idle" : "");
    // the status of record sits on the top line; the goal line keeps the goal (John, 2026-09-25)
    try {
      let line = stat.lead_line || "Next not stated by the steward";
      if (!p.waiting_on_you && stat.eta) line += " · ETA " + stat.eta;
      if (line.length > 120) line = line.slice(0, 117).replace(/\s+\S*$/, "") + "…";
      const barlead = $("[data-barlead]");
      if (barlead) { barlead.textContent = line + (stat.stale ? "  (" + hhmm + ")" : ""); barlead.title = line; }
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
  let _delivOpen = null;   // null until he folds or opens it; starts folded on every open (his word, 2026-10-06)
  function shortWhat(it) {
    return String((it && (it.what || it.label)) || "")
      .replace(/^(?:START HERE|FOR REVIEW|CURRENT)\s*[:\u2014\u2013-]?\s*/i, "")
      .split(" \u2014 ")[0].trim();
  }
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
    try { const im = window.SkillIcons && window.SkillIcons.img(itemMark(it) || "", 14); if (im) line.insertBefore(im, line.firstChild); } catch (e) { /* no-op */ }
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
    const files = h => (Array.isArray(h.outputs) ? h.outputs : []).map(o => typeof o === "string" ? o : (o && (o.path || o.route)) || "").filter(Boolean);
    const empty = [];
    handoffs.forEach((h) => {
      const day = String(h.at || "").slice(0, 10);
      const paths = files(h);
      if (!paths.length) { empty.push(day); return; }
      paths.slice(0, 4).forEach(p => {
        const name = p.split(/[\\/]/).pop();
        const row = el("div", "handoff");
        row.appendChild(el("span", "", (day || "undated") + " \u00b7 "));
        row.appendChild(navFile({what: name, path: p, openable: true}, "handoffs", true));
        const act = el("button", "navactbtn ndact", "act on");
        act.onclick = () => sayAbout("Act on: " + name);
        row.appendChild(act);
        history.appendChild(row);
      });
    });
    if (empty.length) {
      const days = [...new Set(empty.filter(Boolean))].sort();
      const line = empty.length + " turn" + (empty.length === 1 ? "" : "s") + (days.length ? " on " + days.join(", ") : "") + " recorded no files";
      const row = el("div", "handoff");
      row.appendChild(el("span", "", line + " \u00b7 "));
      const act = el("button", "navactbtn ndact", "act on");
      act.onclick = () => sayAbout("Act on: " + line);
      row.appendChild(act);
      history.appendChild(row);
    }
    return history;
  }
  /* Course/product navigation: one event-derived organization for both views. */
  const navStorageKey = () => 'steward_navigation:' + (window.STEWARD_PID || '') + ':' + DIR;
  let navChoices = null;
  // the Not done list starts closed whenever a cockpit opens (his word, 2026-10-06); his click holds while the page
  // lives (the plan repaints on every stamp), and is never restored open from a stored choice on the next open
  const NAV_FRESH = new Set(["plan:notdone"]), navSession = {};
  function fileUrl(p) {
    return "file:///" + String(p).replace(/\\/g, "/").replace(/^\/+/, "").split("/")
      .map((seg, i) => i === 0 && /^[A-Za-z]:$/.test(seg) ? seg : encodeURIComponent(seg)).join("/");
  }
  function navChoice(key, fallback) {
    if (NAV_FRESH.has(key)) return Object.prototype.hasOwnProperty.call(navSession,key) ? navSession[key] : false;
    if (!navChoices) { try { navChoices=JSON.parse(localStorage.getItem(navStorageKey())||'{}'); } catch(e) { navChoices={}; } }
    return Object.prototype.hasOwnProperty.call(navChoices,key) ? navChoices[key] : fallback;
  }
  function navDisclosure(key, title, open=false, mark=null) {
    const d=el('details','navgroup'), summary=el('summary','');
    const marked = !!(mark && mark.glyph);
    if (marked) summary.appendChild(el('span','plan-mark '+mark.cls, mark.glyph));
    summary.appendChild(document.createTextNode((marked ? ' ' : '') + title));
    d.dataset.navGroup=key;summary.dataset.navFocus='group:'+key;
    d.open=navChoice(key,open);d.appendChild(summary);
    const save=value=>{if(NAV_FRESH.has(key)){navSession[key]=value;return;}navChoices[key]=value;try{localStorage.setItem(navStorageKey(),JSON.stringify(navChoices));}catch(e){}};
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
  const itemMark = it => window.SkillIcons ? window.SkillIcons.forItem(it, navOwner((_lastMap && _lastMap.steps) || [], it)) : null;
  function navFile(it, surface, readOnly=false) {
    const box=el('div','navfile');box.dataset.navPath=it.path||it.route||it.what;box.dataset.productId=it.product_id||'';
    const shown={...it,date:String(it.date||'').split('T')[0]};
    if(it.managed && !it.open_path)shown.what=String(it.what||it.product_id).replace(/-/g,' ');
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
            // one decision for a format pair: the product and each verified companion revision of the same presentation
            for(const x of [it,...(it._alsoAccept||[])]) {
              const response=await post('/api/refinement-accept',{step_id:x.step,presentation_id:x.presentation_id,
                product_id:x.product_id,revision_id:x.revision_id,hash:x.hash});
              const result=await response.json();if(!response.ok||!result.ok)throw Error(result.error||'Approval failed');
            }
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
    s.textContent=`.navtree{min-width:0;font-size:13px;line-height:1.42}.navgroup{margin:5px 0;border-top:1px solid #ffffff20;min-width:0}.navgroup>summary{cursor:pointer;padding:8px 3px;font-weight:600;white-space:normal;overflow-wrap:anywhere}.navgroup>summary:has(.plan-mark){list-style:none}.navgroup>summary:has(.plan-mark)::-webkit-details-marker{display:none}.navcontents{padding:0 0 5px 9px;min-width:0}.navgroup .navgroup .navcontents{padding-left:7px}.navfile{padding:5px 0;overflow-wrap:anywhere;border-bottom:1px solid #ffffff0b}.navfile .drow{white-space:normal;overflow:visible;font-size:13px;line-height:1.42}.navfile a{white-space:normal;overflow-wrap:anywhere}.navpin{padding:10px;margin:0 0 10px;border:1px solid #679cc077;border-radius:6px;background:#44698718}.navpin-title{font-size:14px;font-weight:600;margin:3px 0}.naveyebrow{font-size:11px;text-transform:uppercase;letter-spacing:.06em;opacity:.8}.navstep-list{padding:0!important;list-style:none}.navstep-list>li{padding:6px 0!important}.navstep-list .sdeliv{display:none}.navstep-list .sdeliv:has(button){display:block}.navempty{opacity:.75;padding:5px 0;font-size:12px}.navtree .navsupport{margin-top:7px}.navtree .navsupport>summary{font-size:12px;font-weight:400}.navtree .wpkind{display:none}.navtree .navstep-list .stitle{white-space:normal}.navtree .navstep-list .sdmeta{font-size:12px}.navtree .navfile .navgroup{font-size:12px}.navtree .navfile .navgroup>summary{padding:3px;font-weight:400}`;
    s.textContent+='[data-delivmount] .blk.deliv:not(.folded)>.body,[data-delivmount] .blk.next:not(.folded)>.body{max-height:min(52vh,500px);overflow-y:auto;overflow-x:hidden;overscroll-behavior:contain;padding-right:6px}';
    document.head.appendChild(s);
  }
  function renderNavigation(target,map,items,surface,stepRows=null) {
    const model=navModel(map,items);if(!model && stepRows)return false;navStyle();target.classList.add('navtree');
    const pin=(map?.steps||[]).find(s=>s.navigation&&s.navigation.pin);
    if(!stepRows) {
      const p=el('div','navpin');p.appendChild(el('div','naveyebrow','Current work and review'));
      const current=items.filter(i=>i.is_current===true)   // the server's one rule (current_review_items)
        .sort((a,b)=>Number(/^START HERE\b/.test(b.what||''))-Number(/^START HERE\b/.test(a.what||'')) || String(b.date||'').localeCompare(String(a.date||'')));
      if(current.length){
        p.appendChild(el('div','naveyebrow','Files awaiting you \u00b7 '+current.length));
        current.forEach(it=>p.appendChild(navFile(it,surface+':pin',true)));
      } else p.appendChild(el('div','navempty','No files awaiting review.'));
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
      if(!steps.length) return {glyph:'',cls:'todo'};
      if(steps.every(s=>stepDone(s.step))) return {glyph:'✓',cls:'done'};
      if(steps.some(s=>stepNeedsAttention(s.step))) return {glyph:'⚑',cls:'flag'};
      if(steps.some(s=>isNow(s.step,map))) return {glyph:'●',cls:'now'};
      return {glyph:'',cls:'todo'};
    };
    function renderReferences(g,parent,refSurface) {
      const steps=g.referenceSteps||[],items=g.referenceItems||[];
      if(!steps.length&&!items.length)return;
      const shared=navDisclosure(refSurface+':shared:'+g.id,'Shared work and deliverables');
      if(steps.length){
        const list=el('ul','navstep-list');
        steps.forEach(s=>{
          const row=el('li','navstep-reference'),done=stepDone(s.step),attention=stepNeedsAttention(s.step),now=isNow(s.step,map);
          row.dataset.stepRef=s.step.id||String(s.index);
          row.appendChild(el('span','plan-mark '+(done?'done':attention?'flag':now?'now':'todo'),done?'✓':attention?'⚑':now?'●':''));
          row.appendChild(document.createTextNode(' '+(s.step.name||s.step.id||'Step '+(s.index+1))));
          list.appendChild(row);
        });
        shared.appendChild(list);
      }
      items.forEach(it=>shared.appendChild(navFile(it,refSurface+':reference:'+g.id,true)));
      parent.appendChild(shared);
    }
    function renderGroup(g,parent) {
      // the sequence stays open; done, parked and supporting steps fold
      const offPath=st=>stepDone(st)||st.status==='parked';
      const d=navDisclosure(surface+':'+g.id,g.label,false,groupMarkInfo(g)),body=el('div','navcontents');
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
    model.roots.forEach(g=>renderGroup(g,target));   // one tree for the plan and the deliverables tile (John, 2026-09-23)
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
      row.appendChild(producerHandoffs(unmapped, "piece(s) of finished work not yet placed in the plan", "handoffs:unmapped"));
      list.appendChild(row);
    }
    map.steps.forEach((st, i) => {
      const info = planMarkInfo(st, map);
      const li = el("li", info.row);
      li.dataset.stepId=st.id;stepRows.set(i,li);
      li.appendChild(el("span", "mark " + info.cls, info.glyph));
      const wrap = el("div");
      // a flex item defaults to min-width:auto, which nowrap text resolves to
      // the full string width — the rail then grows a horizontal scrollbar
      // instead of ellipsizing the blue line
      wrap.style.minWidth = "0";
      const title = el("div", "stitle");
      if (st.part) title.appendChild(el("span", "wpkind", st.part));
      // (2026-09-05, John) a step that names a skill carries its mark
      try {
        const S = window.SkillIcons, e = S && S.entryFor(String(st.commissioned_as || "").split(":")[0] + " " + st.name);
        const _sk = e && S.img(e.name, 16);
        if (_sk) title.appendChild(_sk);
      } catch (e) { /* no-op */ }
      title.appendChild(document.createTextNode((st.navigation && st.navigation.label) || st.name));
      // W0b: an initiative's heading step wears its tier and life area
      if (st.tier || st.area) title.appendChild(el("span", "wpkind", (st.tier ? "tier " + st.tier : "") + (st.tier && st.area ? " \u00b7 " : "") + (st.area || "")));
      if (st.due) {
        const due = el("span", "sdue", "· due " + fmtDue(st.due));
        due.style.cssText = "color:var(--faint);font-size:11.5px;margin-left:6px;white-space:nowrap";
        title.appendChild(due);
      }
      wrap.appendChild(title);
      // W0b (High Seat, 2026-09-26): a part that points at another record shows what that record
      // says - kind, project, step or deliverable, its state, its date - and a link into it.
      // The Campaign never copies those; a broken reference is named here, never blank.
      // The line sits under the step's title; a project part carries its cockpit's lead line.
      const rs = st.ref ? ((map.resolved || {})[st.id] || null) : null;
      if (st.ref) {
        const line = el("div", "sdmeta sref");
        line.style.cssText = "color:var(--faint);font-size:11.5px";
        if (rs && !rs.broken) {
          line.appendChild(document.createTextNode("\u2192 " + rs.kind + " \u00b7 " + (rs.name || "")
            + (rs.what ? " \u00b7 " + rs.what : "") + (rs.state ? " \u00b7 " + rs.state : "")
            + (rs.date ? " \u00b7 due " + fmtDue(rs.date) : "")
            + (rs.kind === "project" && rs.lead ? " \u00b7 " + oneLine(String(rs.lead), 140) : "") + " "));
          if (rs.href) {
            const a = el("a", "", "open the cockpit");
            a.href = rs.href; a.target = "_blank"; a.rel = "noopener";
            a.onclick = (event) => event.stopPropagation();
            line.appendChild(a);
          }
        } else {
          line.appendChild(document.createTextNode("\u2192 " + st.ref + " \u00b7 broken reference: " + ((rs && rs.gap) || "not resolved")));
          line.style.color = "var(--bad, #e06c75)";
        }
        wrap.appendChild(line);
      }
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
    list.appendChild(notDoneList(map, stepRows));
    if (STEP && !_stepShown) {
      const row = list.querySelector('li[data-step-id="' + STEP.replace(/"/g, '') + '"]');
      if (row) {
        _stepShown = true;
        // a done or parked step sits inside a closed disclosure: open every fold above it first, so the landing
        // is on the plan he can see (Grok W5); the mark is the cockpit's own class, one ring for a moment
        for (let anc = row.parentElement; anc && anc !== list; anc = anc.parentElement) {
          if (anc.tagName === "DETAILS" && !anc.open) anc.open = true;
        }
        row.scrollIntoView({block: "center"});
        row.classList.add("navstep-land");
        setTimeout(() => row.classList.remove("navstep-land"), 2400);
      }
    }
  }
  function sayAbout(text) {
    const ta = $("[data-say]");
    if (!ta) return;
    const line = text + "\n";
    ta.value = (!ta.value.trim() || /^Act on: /.test(ta.value)) ? line : ta.value.replace(/\s*$/, "\n") + line;
    ta.focus();
    ta.scrollIntoView({block: "nearest"});
  }
  // the red-flag list at the bottom of the plan: every step not done, waiting on you first and in red
  function notDoneList(map, stepRows) {
    const li = el("li", "notdone");
    const supporting = st => !!(st.navigation && st.navigation.role === "support");
    const heldOut = st => !stepDone(st) && !isNow(st, map) && (st.status === "parked" || supporting(st));
    const open = map.steps.map((st, i) => ({st, i})).filter(x => !stepDone(x.st) && !heldOut(x.st));
    const rank = x => stepWaitsOnJohn(x.st) ? 0 : isNow(x.st, map) ? 1 : x.st.status === "active" ? 2 : 3;
    open.sort((a, b) => rank(a) - rank(b) || a.i - b.i);
    const box = navDisclosure("plan:notdone", "Not done \u00b7 " + open.length);   // closed on open; a click opens it
    open.forEach(x => {
      const wait = stepWaitsOnJohn(x.st), bare = wait === "waiting" || wait === "blocked", now = isNow(x.st, map);
      const label = (x.st.navigation && x.st.navigation.label) || x.st.name;
      const row = el("div", "notdonerow" + (wait ? " waits" : ""));
      const head = el("div", "ndhead");
      head.appendChild(el("span", "mark" + (now && !wait ? " now" : ""), wait ? "\u2691" : now ? "\u25cf" : ""));
      const name = el("button", "navactbtn", label);
      name.onclick = () => {
        const target = stepRows.get(x.i);
        if (!target) return;
        _openSteps.add(x.st.id || x.st.name || String(x.i));
        target.classList.add("open");
        for (let d = target.closest("details"); d; d = d.parentElement && d.parentElement.closest("details")) d.open = true;
        target.scrollIntoView({block: "nearest"});
      };
      head.appendChild(name);
      row.appendChild(head);
      const line = el("div", "ndline");
      const state = wait ? ((now ? "now \u00b7 " : "") + (wait === "blocked" ? "blocked" : "waiting on you")) : now ? "now" : x.st.status === "active" ? "in progress" : (x.st.status || "planned");
      if (wait && !bare) {
        const d = el("details", "ndwait"), key = "plan:notdone:" + (x.st.id || x.st.name || String(x.i));
        d.open = navChoice(key, false);
        d.addEventListener("toggle", () => { if (d.isConnected) { navChoices[key] = d.open; try { localStorage.setItem(navStorageKey(), JSON.stringify(navChoices)); } catch (e) {} } });
        d.appendChild(el("summary", "", state));
        d.appendChild(el("div", "ndwaittext", wait));
        line.appendChild(d);
      } else line.appendChild(el("span", "notdonestate", state));
      const act = el("button", "navactbtn ndact", "act on");
      act.title = "Put this item into the dialogue";
      act.onclick = () => sayAbout("Act on: " + label + " \u2014 " + state + (wait && !bare ? ": " + wait : ""));
      line.appendChild(act);
      row.appendChild(line);
      box.appendChild(row);
    });
    const held = map.steps.filter(heldOut), parked = held.filter(st => st.status === "parked").length, support = held.length - parked;
    if (!open.length) box.appendChild(el("div", "navempty", held.length ? "Nothing open beyond the parked and supporting steps." : "Every step is done."));
    li.appendChild(box);
    if (held.length) li.appendChild(el("div", "planlegend", [parked ? "Parked \u00b7 " + parked : "", support ? "Supporting steps \u00b7 " + support : ""].filter(Boolean).join(" \u00b7 ") + " \u2014 kept out of Not done"));
    li.appendChild(el("div", "planlegend", "\u2713 done \u00b7 \u25cf now \u00b7 \u2691 waiting on you"));
    return li;
  }
  // Readable opening copies are bound to exact immutable revisions in the ONE
  // DELIVERABLES register: `named file` review: `immutable file`. The route
  // still checks the revision hash; labels never change lifecycle identity.
  function registeredReviewNames(items, approved = [], acts = []) {
    const key = p => String(p || '').replace(/\\/g, '/');
    const contained = p => typeof p === 'string' && p.length > 0 && p.length <= 1000 &&
      !/[\\:\x00-\x1f]/.test(p) && !p.startsWith('/') &&
      p.split('/').every(x => x && x !== '.' && x !== '..');
    const aliases = new Map();
    for (const row of items) {
      if (row.managed || !row.openable || !contained(row.path)) continue;
      const match = /\breview:\s*`([^`]+)`/.exec(row.where_text || '');
      if (!match || !contained(match[1]) || key(match[1]) === key(row.path)) continue;
      const binding = key(match[1]);
      const owner = row.owner_step_id || row.step;
      if (!owner || !row.what) continue;
      const entry = {owner, label: row.what, open_path: row.path};
      if (aliases.has(binding) && JSON.stringify(aliases.get(binding)) !== JSON.stringify(entry))
        aliases.set(binding, null); // Ambiguous labels cannot replace an exact revision.
      else if (!aliases.has(binding)) aliases.set(binding, entry);
    }
    const decorate = item => {
      const a = item && aliases.get(key(item.path));
      const owner = item && (item.owner_step_id || item.step || item.step_id);
      const ext = p => key(p).split('/').pop().split('.').pop().toLowerCase();
      const named = item && item.managed && /^[a-f0-9]{64}$/i.test(item.hash || '') &&
        a && a.owner === owner && ext(item.path) === ext(a.open_path)
        ? {...item, what: a.label, open_path: a.open_path} : {...item};
      if (item && item.history) named.history = item.history.map(decorate);
      return named;
    };
    const decorated = items.map(decorate);
    const openingCopies = new Set(decorated.filter(i => i.managed && i.open_path && i.is_current)
      .map(i => key(i.open_path)));
    return {items: decorated.filter(i => i.managed || !openingCopies.has(key(i.path))), approved: approved.map(decorate),
      acts: acts.map(a => a.item ? {...a, item: decorate(a.item), label: decorate(a.item).what} : a)};
  }
  async function renderDeliverablesTile() {
    if (_delivBusy) return;
    _delivBusy = true;
    let d = null;
    try { d = await (await fetch(api("/api/deliverables"))).json(); }
    catch (e) { _delivBusy = false; return; }
    _delivBusy = false;
    const named = registeredReviewNames((d && d.items) || [], (d && d.approved) || [], (d && d.acts) || []);
    const items = named.items;
    const focusKey=document.activeElement && document.activeElement.dataset.navFocus;
    _deliv = {...named, warning: (d && d.current_warning) || ""};
    renderNextStepsTile();
    // repaint the plan so step-tagged deliverables land under their steps
    if (_lastMap) { try { paintStepsList(_lastMap); } catch (e) {} }
    // — the tile: its OWN slot above the scrollport when the page provides
    //   one (never overlaps the status blocks), else the pane as before —
    const s = $("[data-delivmount]") || paneEl();
    if (s) {
      let tile = s.querySelector(".blk.deliv");
      const priorScroll=tile && tile.querySelector(".body") ? tile.querySelector(".body").scrollTop : 0;
      // starts CLOSED so the status keeps the room - even with current files (his word, 2026-10-06: the lists must not
      // open up by themselves when a cockpit opens); his choice then sticks for this page
      const currentNow = items.filter(i => i.is_current === true)
        .sort((a,b) => Number(/^START HERE\b/.test(b.what||''))-Number(/^START HERE\b/.test(a.what||'')) || String(b.date || '').localeCompare(String(a.date || '')));
      const wasOpen = tile ? !tile.classList.contains("folded") : _delivOpen === true;
      if (!tile) {
        tile = el("div", "blk steward deliv" + (wasOpen ? "" : " folded"));
        s.insertBefore(tile, s.firstChild);
      } else tile.textContent = "";
      if (wasOpen) tile.classList.remove("folded");
      else tile.classList.add("folded");
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
      const names = currentNow.map(shortWhat).filter(Boolean).slice(0, 2)
        .map(t => t.length > 42 ? t.slice(0, 41).replace(/\s+\S*$/, "") + "\u2026" : t);
      const who = el("div", "who",
        "DELIVERABLES \u00b7 " + (currentNow.length
          ? currentNow.length + " for you" + (names.length ? " \u2014 " + names.join(" \u00b7 ") : "")
          : (items.length ? items.length + " registered" + (newest ? " \u2014 " + newest : "")
                          : "nothing registered yet")));
      who.style.cursor = "pointer";
      who.onclick = () => {
        tile.classList.toggle("folded");
        _delivOpen = !tile.classList.contains("folded");
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
    try {
      // (2026-10-07) a Foundry review route is named by its skill — the live
      // page it opens — never the raw query string
      const sk = /^\/foundry\?skill=([^&]+)$/.exec(String(r || ""));
      if (sk) return decodeURIComponent(sk[1]) + " — live Foundry page";
      const m = /[?&]path=([^&]+)/.exec(r); const seg = decodeURIComponent(m ? m[1] : r).split("/").filter(Boolean); return seg[seg.length - 1] || r;
    }
    catch (e) { return r; }
  }
  function delivRow(it) {
    const row = el("div", "snow drow");
    const openPath = it.open_path || it.path;
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
      try { const im = window.SkillIcons && window.SkillIcons.img(itemMark(it) || "", 14); if (im) a.insertBefore(im, a.firstChild); } catch (e) { /* no-op */ }
      a.href = routeHref(it.route);
      a.target = "_blank";
      a.rel = "noopener";
      row.appendChild(a);
    } else if (it.openable && it.path) {
      const a = document.createElement("a");
      a.textContent = "• " + it.what;
      try { const im = window.SkillIcons && window.SkillIcons.img(itemMark(it) || "", 14); if (im) a.insertBefore(im, a.firstChild); } catch (e) { /* no-op */ }
      // 2026-08-26 (John: "I click on them and the page had nothing"): a raw
      // <a href> NAVIGATES — it never passes through the fetch shim, so the
      // old api() URL arrived with no /api/steward/ prefix, no pid and no
      // token → a blank page. Build the FULL authed URL ourselves, and send
      // text docs (.md/.txt/.csv/.json/.log) through the report VIEWER so
      // they render human-readable instead of as raw bytes.
      const dirRel = it.dir !== undefined ? it.dir : DIR;
      const isText = /\.(csv|json|log)$/i.test(openPath) && !(it.managed && it.open_path && it.hash);
      // 2026-10-07 (item 2): markdown opens through the ONE canonical reading URL (deliverables_register.reading_target:
      // deliverable-file + render=1) - the same link the dialogue's receipt and Next steps carry
      const isMarkdown = /\.(md|markdown|txt)$/i.test(openPath);
      const reading = it.reading && it.reading.read && /^\/api\/steward\/deliverable-file\?/.test(it.reading.read) ? it.reading.read : "";
      const tok = window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "";
      if (reading) {
        // the server's reading target (deliverables_register.reading_target) - the receipt's URL, token added
        a.href = reading + tok;
        a.target = "_blank";
        a.rel = "noopener";
      } else if (it.reading && it.reading.preparing) {
        // nothing renders yet (a deck without its PDF): say so - never a link to an "unavailable" page
        const label = el("span", "preparing", "• " + it.what + " · preparing a reading copy");
        row.appendChild(label);
        if (it.reading.download) {
          const d = el("a", "ddl", "Download");
          d.href = it.reading.download + tok; d.target = "_blank"; d.rel = "noopener";
          row.appendChild(document.createTextNode(" ")); row.appendChild(d);
        }
        return row;
      } else if (isText) {
        a.href = "#";
        a.onclick = (ev) => { ev.preventDefault();
          window.open("/report?dir=" + encodeURIComponent(dirRel) +
                      "&path=" + encodeURIComponent(openPath)); };
      } else {
        a.href = "/api/steward/deliverable-file?pid=" +
          encodeURIComponent(window.STEWARD_PID || "") +
          "&dir=" + encodeURIComponent(dirRel) +
          "&path=" + encodeURIComponent(openPath) +
          (it.hash ? "&hash=" + encodeURIComponent(it.hash) : "") +
          (/\.(docx|pptx|xlsx)$/i.test(it.path) ? "&view=1" : "") +
          (isMarkdown ? "&render=1" : "") +
          (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "");
        a.target = "_blank";
        a.rel = "noopener";
      }
      row.appendChild(a);
      if(/\.pptx$/i.test(it.path)) {
        const download=el('a','sdmeta',' Download PowerPoint');
        // the deck's own download (the reading link may be its PDF companion - never download that as the deck)
        download.href=(it.reading&&it.reading.download)?it.reading.download+(window.STEWARD_TOKEN?'&token='+encodeURIComponent(window.STEWARD_TOKEN):''):a.href.replace(/&view=1\b/,'')+'&download=1';download.target='_blank';download.rel='noopener';row.appendChild(download);
      }
      if (/\.docx$/i.test(it.path) && it.dir === undefined && _lastMap && _lastMap.dir) {
        // (Wave D0) one click opens the manuscript in desktop Word, track changes and all
        const word = el('a', 'sdmeta', ' Open in Word');
        word.href = "ms-word:ofe|u|" + fileUrl(_lastMap.dir) + "/" + String(openPath).split(/[\\/]/).map(encodeURIComponent).join("/");
        row.appendChild(word);
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
          const target = isText ? "/steward/report?pid=" + encodeURIComponent(window.STEWARD_PID || "") + "&dir=" + encodeURIComponent(dirRel) + "&path=" + encodeURIComponent(openPath) + (it.hash ? "&hash=" + encodeURIComponent(it.hash) : "") + (window.STEWARD_TOKEN ? "&token=" + encodeURIComponent(window.STEWARD_TOKEN) : "") : href;
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
      actEl.querySelector(".actlabel").textContent =
        "✓ " + n + (n === 1 ? " step" : " steps") + " — click to see what it did";
    }
    actEl = null; actSteps = []; actStart = 0; actHome = null;
  }
  // the skill a tool use runs: a Skill tool names it; a read under skills/<name>/ names it by its folder
  function skillOfTool(ev) {
    const S = window.SkillIcons;
    if (!S) return null;
    const exact = t => { t = String(t || "").toLowerCase(); return t ? (S.MAP.find(m => m.name.toLowerCase() === t || m.aliases.indexOf(t) >= 0) || null) : null; };
    const detail = String(ev.detail || "");
    const m = /(?:^|[\\/\s"'])skills[\\/]([^\\/\s"']+)[\\/]/i.exec(detail);
    return (m && exact(m[1])) || exact(detail.split(/\s+/)[0]);
  }
  function activity(ev) {
    const step = (ev.name || "?") + (ev.detail ? " " + ev.detail : "");
    const sk = skillOfTool(ev);
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
      head.appendChild(el("span", "actlabel", ""));
      const body = el("div", "actbody");       // actEl and the old closure then
      head.onclick = () => box.classList.toggle("open");  // threw / hit the
      box.appendChild(head);                   // wrong line
      box.appendChild(body);
      s.appendChild(box);
      actEl = box;
      pin(s, stick);
      actTimer = setInterval(() => {
        if (!actEl || !actEl.isConnected) { resetActivity(); return; }
        actEl.querySelector(".actlabel").textContent = actLabel();
      }, 1000);
    }
    actEl.querySelector(".actlabel").textContent = actLabel();
    const line = el("div", "actstep");
    if (sk) {
      const head = actEl.querySelector(".acthead"), old = head.querySelector(".skico");
      if (old) old.remove();
      const im = window.SkillIcons.img(sk.name, 16);
      if (im) head.insertBefore(im, head.firstChild);
      const li = window.SkillIcons.img(sk.name, 14);
      if (li) line.appendChild(li);
    }
    line.appendChild(document.createTextNode("· " + step));
    actEl.querySelector(".actbody").appendChild(line);
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
    box.querySelector(".actlabel").textContent =
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
      tileSay("turn", { who: "you", text: String(ev.text || "").slice(-600) });
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
    } else if (ev.t === "receipt") {
      // the engine's delivery receipt (item 2): one line, the Read link the Deliverables tile also carries
      closeCurrent();
      addBlock("steward", "ANCHOR", ev.text, "receipt");
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
      // R1 (2026-10-04): a queued receipt carries "Take this now" - the running turn ends, his message goes at once
      if (ev.take_now) {
        const s = targetFor(ev), line = s && s.lastElementChild;
        if (line) {
          const b = el("button", "take-now", "Take this now");
          b.type = "button";
          b.onclick = async () => { b.disabled = true; b.textContent = "Taking it now\u2026";
            let ok = false;
            try { const r = await post("/api/engine", { action: "take_now" }); const j = await r.json(); ok = r.ok && j && j.ok; } catch (e) { ok = false; }
            if (!ok) { b.disabled = false; b.textContent = "Take this now"; b.title = "the turn could not be taken over - try again"; } };
          line.appendChild(document.createTextNode(" ")); line.appendChild(b);
        }
      }
    }
    if (opts.onEvent) opts.onEvent(ev);
  }

  let epoch = null;
  async function poll() {
    for (;;) {
      if (parked) { await new Promise(res => { _unpark = res; }); continue; }
      try {
        _pollAbort = new AbortController();
        const r = await fetch(api("/api/events?since=" + seq), { signal: _pollAbort.signal });
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
        if (j.stamp && j.stamp !== stamp) { const was = stamp; stamp = j.stamp; await loadMap(); if (was) tileSay("stamp", { stamp: stamp }); }
      } catch (e) {
        if (parked) continue;   // the park cut the long-poll; nothing failed
        await new Promise(res => setTimeout(res, 3000));
      }
    }
  }

  // a cheap idle repaint so the map also refreshes when the steward is quiet
  // or files change from outside this engine (not only on streamed events)
  async function stampPoll() {
    for (;;) {
      await new Promise(res => setTimeout(res, 3500));
      if (parked) continue;
      try {
        const r = await fetch(api("/api/state"));
        const j = await r.json();
        updateState(j);
        // A reader can observe projection publication between its writes.
        // Recheck reported inconsistency even if no later event changes stamp.
        if ((j.stamp && j.stamp !== stamp) || map?.refinement?.consistent === false) {
          const was = stamp, moved = !!(j.stamp && j.stamp !== stamp);
          if(j.stamp)stamp=j.stamp;
          await loadMap();
          await renderDeliverablesTile();
          if (moved && was) tileSay("stamp", { stamp: stamp });
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
  // the one state rule: the light's colour and its short word (the pane, the project dot and the bar read it)
  function stateColor(st) {
    const attention = (_lastMap && _lastMap.attention) || {};
    const attentionState = st.attention_state || attention.state || "";
    const working = st.busy || st.working_bg || (st.alive && st.queued);
    return st.light === "red" ? "red" : working ? "green"
      : (st.open_question || ["needs_you", "blocked"].includes(attentionState)) ? "orange" : "quiet";
  }
  function stateWord(st) {
    const color = stateColor(st), attention = (_lastMap && _lastMap.attention) || {};
    const attentionState = st.attention_state || attention.state || "";
    return color === "red" ? "needs a look" : color === "green" ? "working"
      : color === "orange" ? ((st.open_question || attentionState === "needs_you") ? "need your input" : "blocked") : "";
  }
  function syncCompactActivity(st) {
    if(!st)return;
    const value=liveActivityWord(st);
    const chip=$('.blk.status.latest [data-live-activity]');
    if(chip){chip.textContent=value;chip.title=value;}
    paintActionNeeded($('[data-openq]'));
    paintActionNeeded($('[data-status-action]'));
    renderNextStepsTile();
  }

  function updateState(st) {
    if (st) { lastState = st; tileSay("state", { light: st.light || "", busy: !!st.busy, alive: !!st.alive, queued: st.queued || 0, word: stateWord(st) || "" }); }
    st = lastState;
    if (!st) return;
    if(_answerQuestionId && !(st.pending_questions||[]).some(q=>q.id===_answerQuestionId))_answerQuestionId=null;
    const busy = $("[data-busy]");
    if (busy) {
      const word = stateWord(st);
      busy.textContent = st.busy
        ? ((st.quiet_seconds || 0) >= 300
            ? "thinking " + Math.round(st.quiet_seconds / 60) + " min, no output - Stop turn interrupts"
            : (busySince ? "thinking " + Math.round((Date.now() - busySince) / 1000) + "s"
                         : "working..."))
        : (word ? "\u00b7 " + word : "");
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
      const num = v => (typeof v === "number" && Number.isFinite(v) && v >= 0) ? v : 0;
      const priced = [effortUsage, jobsUsage, seats].filter(Boolean);
      const sessionOnly = !effortUsage;
      const reportedTotal = priced.reduce((a, b) => a + num(b.reported_spend), 0) + (sessionOnly ? num(knownSessionUsd(st.reported_spend_usd) ? st.reported_spend_usd : st.spend_usd) : 0);
      const unpricedTotal = priced.reduce((a, b) => a + num(b.unpriced_turns), 0) + (sessionOnly ? num(st.unpriced_turns) : 0);
      const tokensTotal = [effortUsage, jobsUsage, kids, seats].filter(Boolean).reduce((a, b) => a + num(b.tokens), 0) + (sessionOnly ? num(st.tokens) : 0);
      const unknownTotal = [jobsUsage, kids, seats].filter(Boolean).reduce((a, b) => a + num(b.unknown), 0);
      const fam = String((effortUsage || st).billing_family || "");
      const subName = fam === "mixed" ? "ChatGPT/Grok" : fam === "grok" ? "Grok" : fam === "chatgpt" ? "ChatGPT" : "";
      const estimatedTotal = priced.reduce((a, b) => a + num(b.estimated_spend), 0) + (sessionOnly ? num(st.estimated_spend_usd) : 0);
      const estimatedTurns = priced.reduce((a, b) => a + num(b.estimated_turns), 0) + (sessionOnly ? num(st.estimated_turns) : 0);
      const stillUnpriced = Math.max(0, unpricedTotal - estimatedTurns);
      const estimated = estimatedTurns ? "about $" + estimatedTotal.toFixed(2) + " estimated for " + estimatedTurns.toLocaleString() + " ChatGPT turn" + (estimatedTurns === 1 ? "" : "s") + " at API list price" : "";
      const notPriced = stillUnpriced ? stillUnpriced.toLocaleString() + (subName && !estimatedTurns ? " " + subName + " turn" + (stillUnpriced === 1 ? "" : "s") : "") + " with no dollar amount" : "";
      let total = reportedTotal > 0 ? "Total $" + reportedTotal.toFixed(2) + " reported" + (estimated ? " + " + estimated : "") + (notPriced ? " · " + notPriced : "")
        : estimated ? "Total " + estimated + (notPriced ? " · " + notPriced : "")
        : notPriced ? "Total: " + notPriced : "cost unavailable";
      if (tokensTotal) total += " · " + Math.round(tokensTotal).toLocaleString() + " tokens recorded";
      if (unknownTotal) total += " · " + unknownTotal + " run" + (unknownTotal === 1 ? "" : "s") + " with unknown usage";
      spend.textContent = total +
        (st.usage_persistence_error ? " · not saved" : "") +
        (!st.alive ? " · " + (GENERAL ? "idle" : "steward asleep") + (st.queued ? " · " + st.queued + " held" : "") : "");
      if (!effortUsage) spend.title = "Session: " + sessionCostText + sessionTokensText;
      if (jobsText) spend.title += " · Delegated jobs" + jobsText.replace(/^ · /, ": ") + " · " + recordedTokenText(jobsUsage);
      if (kidsText) spend.title += " · Sub-agents" + kidsText.replace(/^ · /, ": ");
      if (seatsText) spend.title += " · Skill seats" + seatsText.replace(/^ · /, ": ") + " · " + recordedTokenText(seats);
      spend.title += " · Reported dollars are recorded charges." +
        (estimatedTurns ? " Estimated dollars come from each ChatGPT turn's recorded tokens at OpenAI's published " + (st.estimate_basis || "API list price") + ", never a charge; the subscription bills a flat fee." : "") +
        (stillUnpriced ? " Subscription turns recorded without a token split, or on a model outside the price table, carry no dollar amount." : "");
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
    const color = stateColor(st);
    const light = $("[data-light]"), light2 = $("[data-light2]");
    if (light) light.className = "light " + color;
    if (light2) light2.className = "light " + color;
    const projectLight=$('[data-att]');
    if(projectLight){projectLight.className='dot light '+color;projectLight.title=stateWord(st)||'Idle';}
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
    // W2 (High Seat, 2026-09-26): the upload place sits at the TOP of the Files section (John):
    // drop or pick, one POST per file through the effort's own upload verb; the list repaints
    // with the next state refresh, and the line here says what happened to each file.
    const up = $("[data-fupload]");
    if (up && !up._wired) {
      up._wired = true;
      const msg = $("[data-fupmsg]"), pick = $("[data-fupfile]");
      const say = (text) => { if (msg) msg.textContent = " · " + text; };
      const send = async (file) => {
        const b64 = await new Promise((res, rej) => {
          const r = new FileReader();
          r.onload = () => res(String(r.result).split(",")[1] || "");
          r.onerror = () => rej(new Error("read failed"));
          r.readAsDataURL(file);
        });
        const resp = await post("/api/upload", { name: file.name, data_b64: b64, mode: "new", sub: "" });
        const j = await resp.json().catch(() => ({}));
        if (j && j.ok) {
          say("loaded " + file.name);
          try { _lastFiles = (_lastFiles || []).concat([{ name: file.name, path: file.name, at: new Date().toISOString(), loaded: true }]); renderFiles(_lastFiles); } catch (e) { /* the next refresh paints it */ }
        }
        else if (j && j.exists) say(file.name + " is already there — nothing overwritten");
        else say(((j && j.error) || "not loaded") + " (" + file.name + ")");
      };
      const queue = (files) => Array.from(files || []).forEach((f) => send(f).catch(() => say("not loaded (" + f.name + ")")));
      up.ondragover = (e) => { e.preventDefault(); up.classList.add("hot"); };
      up.ondragleave = () => up.classList.remove("hot");
      up.ondrop = (e) => { e.preventDefault(); up.classList.remove("hot"); queue(e.dataTransfer.files); };
      if (pick) pick.onchange = () => { queue(pick.files); pick.value = ""; };
    }
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
    const cockpitName = !DIR && map.name === "Campaign" ? (window.STEWARD_MODE || (map.steward === "Aladdin" ? "Star Chart" : map.name)) : map.name;
    const cockpitTitle = cockpitName + " — AI Cockpit";
    document.title = GENERAL ? map.name + " — steward" : cockpitTitle;
    if (opts.renderMap) { opts.renderMap(map); return; }
    // goal tile (one sentence; expands to the full bold-led description)
    const gb = $("[data-goalbrief]");
    if (gb) gb.textContent = map.goal_brief || "";
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
    if (name) name.textContent = GENERAL ? map.name : cockpitTitle;
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
    if (j.turns && j.turns.length) {
      addLine("divider", "—— live from here ——");
      const last = j.turns[j.turns.length - 1];
      tileSay("turn", { who: last.role === "john" ? "you" : "steward", text: String(last.text || "").slice(-600) });
    }
    { const d = scrollEl(); if (d) d._follow = true; pin(d, true); }   // a page opens at the newest
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
    // R12 (2026-09-28, John: "conversations are saved as they are put in"): the unsent text is kept in this browser
    // on every keystroke (localStorage, keyed to this record) and put back after a crash, a restart or a reload of
    // the page; a delivered turn clears it, an undelivered one keeps it
    const DRAFT_KEY = "anchor:draft:say:" + (PARAMS.get("pid") || "") + ":" + DIR + (TILE ? ":tile" : "");   // the tile's own words, never the cockpit tab's (ChatGPT 2026-10-02)
    let _draftT = null;
    const saveDraft = () => { try { if (ta.value.trim()) localStorage.setItem(DRAFT_KEY, ta.value); else localStorage.removeItem(DRAFT_KEY); } catch (e) {} };
    const clearDraft = () => { try { localStorage.removeItem(DRAFT_KEY); } catch (e) {} };
    ta.addEventListener("input", () => { clearTimeout(_draftT); _draftT = setTimeout(saveDraft, 250); });
    ta.addEventListener("blur", saveDraft);  // the app blurs a composer before dropping its inactive frame
    window.addEventListener("beforeunload", saveDraft);
    try {
      const kept = localStorage.getItem(DRAFT_KEY);
      if (kept && kept.trim() && !ta.value.trim()) { ta.value = kept; grow(); addLine("sys", "your unsent text is back in the box"); }
    } catch (e) {}
    const submit = async () => {
      let text = ta.value.trim();
      if (!text) return;
      // dictation-friendly grasscatch: "later: ..." parks it without ceremony
      const later = text.match(/^(later|grasscatcher?)[:,]\s*(.+)/is);
      if (later) text = "Grasscatch this (park it on the Strip with a reason, " +
                        "then carry on with the step in hand): " + later[2];
      const keep = ta.value;
      ta.value = ""; grow();
      { const d = scrollEl(); if (d) { d._follow = true; pin(d, true); } }   // his own message brings him to the newest
      const j = await sendSay(text, _answerQuestionId);
      if (!j.ok) { ta.value = keep; grow(); saveDraft(); } else { clearDraft(); }
    };
    if (send) send.onclick = submit;
    if (TILE) {
      const typing = () => tileSay("typing", { active: !!ta.value.trim() || document.activeElement === ta });
      ta.addEventListener("input", typing); ta.addEventListener("focus", typing); ta.addEventListener("blur", typing);
      window.addEventListener("message", (ev) => {
        const m = ev.data;
        if (ev.origin !== location.origin || ev.source !== window.parent || !m || m.proto !== "anchor-tile" || m.inst !== INST) return;
        if (m.kind === "park" || m.kind === "show") { setParked(m.kind === "park"); return; }
        if (m.kind === "prefill" && typeof m.text === "string") {
          ta.value = ta.value.trim() ? (ta.value.replace(/\s+$/, "") + "\n" + m.text) : m.text;
          ta.dispatchEvent(new Event("input"));
          if (m.focus) { ta.focus(); try { ta.setSelectionRange(ta.value.length, ta.value.length); } catch (e) {} }
        }
      });
      // a file dropped on this view goes to the tile, which lands it in this effort's folder (one route, one receipt)
      document.addEventListener("dragover", (e) => { if (e.dataTransfer && Array.from(e.dataTransfer.types || []).includes("Files")) e.preventDefault(); });
      document.addEventListener("drop", (e) => {
        const files = e.dataTransfer && e.dataTransfer.files;
        if (!files || !files.length || e.defaultPrevented || (e.target && e.target.closest && e.target.closest("[data-fupload], [data-filesect]"))) return;
        e.preventDefault(); tileSay("drop", { files: Array.from(files) });
      });
      tileSay("ready", {});
    }
    // (codex-discipline-2026-09-15 Wave 1.2) Send is disabled in the markup
    // and enabled only once its handler exists: a click in the load window
    // used to produce neither a POST nor a record.
    if (send) send.disabled = false;
    ta.addEventListener("keydown", (e) => {
      // 2026-10-07 (John, evidence E5: a late dictated "new line" sent a fragment): Enter is ALWAYS a new line;
      // Ctrl+Enter (Cmd+Enter on a Mac) or the Send button sends. Never from a key during an active composition.
      if (e.key !== "Enter" || e.isComposing || e.keyCode === 229) return;
      if (!(e.ctrlKey || e.metaKey)) return;
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
    if (TILE) { const a = document.querySelector(".app"); if (a) { a.classList.add("tileview", "railhide"); if (PARAMS.get("compose") === "0") a.classList.add("nocompose"); } }
    // the steward's dialogue alone (his word, 2026-10-02: "the steward dialogue from an AI Cockpit, maybe the status bar
    // available but thinner, and the plan is not something we have to worry about in those pages")
    if (TALK) { const a = document.querySelector(".app"); if (a) { a.classList.add("talkview", "railhide", "nocompose"); a.classList.remove("statusopen"); } }
    if (opts.stewardLabel) opts._labelSet = true;
    applyTheme();
    try { wireFollow(scrollEl()); } catch (e) {}   // before history loads, so the replay lands at the newest
    try { await loadMap(); } catch (e) {
      const p = $("[data-progress]");
      if (p) p.textContent = "map failed: " + ((e && e.message) || "could not load");
      tileSay("trouble", { text: "this cockpit's record could not be read" + (e && /401|403|auth/i.test(String(e.message || "")) ? " - this browser is not logged in" : "") });
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
