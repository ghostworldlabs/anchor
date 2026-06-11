/* Anchor R&D interactive terminal — lightweight, dependency-free console (Wave 7).
 *
 * SUBSTRATE NOTE: Anchor's runtime is stdlib-only with NO native/compiled
 * assets, so the v2 terminal is NOT a ConPTY/xterm.js terminal — it is a
 * persistent stream-json REPL (one long-lived claude/gemini process per session)
 * given a terminal *feel* by this small console. A real xterm.js bundle exists on
 * some machines but is NOT vendored here to avoid a version-coupled, native-leaning
 * asset; this component is deliberately self-contained and is NAMED so xterm.js can
 * be swapped in later behind the same factory API (window.AnchorTerm.mount).
 *
 * Responsibilities:
 *  - render the SSE stream (GET /api/rnd/term_stream?session=...) as terminal lines
 *  - a command input line that POSTs turns (POST /api/rnd/term_input)
 *  - surface an in-session gate/AskUserQuestion inline as a prompt the user answers
 *    by clicking an option OR by typing a reply
 *  - on process exit, request the adoption proposal and let the user confirm-adopt
 *
 * Pure browser JS, no dependencies. Served as a vendored static asset like KaTeX.
 */
(function () {
  "use strict";

  function el(tag, cls) { var e = document.createElement(tag); if (cls) e.className = cls; return e; }
  function esc(s) { var d = document.createElement("div"); d.textContent = (s == null ? "" : s); return d.innerHTML; }

  // A single terminal instance bound to one session_id.
  function AnchorTerm(opts) {
    this.host = opts.host;                 // container element
    this.sessionId = opts.session;         // job_id of the terminal session
    this.lane = opts.lane || "";
    this.title = opts.title || (this.lane || "terminal");
    this.postJson = opts.postJson;         // token-aware POST helper (from caller)
    this.onAdopted = opts.onAdopted || function () {};
    this.cursor = 0;
    this.status = "running";
    this.pending = null;                   // a pending gate prompt, if any
    this.closed = false;
    this._es = null;                       // EventSource (SSE)
    this._build();
  }

  AnchorTerm.prototype._build = function () {
    this.host.innerHTML = "";
    var root = el("div", "aterm");
    // Title bar.
    var bar = el("div", "aterm-bar");
    this._dot = el("span", "dot live");
    bar.appendChild(this._dot);
    var t = el("span", "title"); t.textContent = this.title; bar.appendChild(t);
    this._statusEl = el("span", "status"); this._statusEl.textContent = "running"; bar.appendChild(this._statusEl);
    root.appendChild(bar);
    // Screen (scrollback).
    this._screen = el("div", "aterm-screen");
    root.appendChild(this._screen);
    // Input row.
    var row = el("div", "aterm-inputrow");
    var pr = el("span", "prompt"); pr.textContent = "›"; row.appendChild(pr);
    this._input = el("input");
    this._input.setAttribute("placeholder", "type a turn and press Enter…");
    this._input.setAttribute("aria-label", "terminal input");
    var self = this;
    this._input.addEventListener("keydown", function (e) {
      if (e.key === "Enter" && self._input.value.trim()) {
        self.sendTurn(self._input.value);
        self._input.value = "";
      }
    });
    row.appendChild(this._input);
    root.appendChild(row);
    this.host.appendChild(root);
    this._input.focus();
  };

  AnchorTerm.prototype.writeLine = function (text, kind) {
    var line = el("div", "aterm-line " + (kind || "assistant"));
    line.textContent = text;
    this._screen.appendChild(line);
    this._screen.scrollTop = this._screen.scrollHeight;
  };

  // Render a server output chunk. The SSE "output" event carries raw stream-json
  // lines from the engine; we surface them verbatim (terminal feel) but tag a
  // best-effort role so user echoes/system notes are distinguishable.
  AnchorTerm.prototype._renderOutput = function (payload) {
    var lines = payload && payload.lines ? payload.lines : [];
    for (var i = 0; i < lines.length; i++) {
      var ln = lines[i];
      this.writeLine(typeof ln === "string" ? ln : JSON.stringify(ln), "assistant");
    }
    if (payload && typeof payload.next === "number") this.cursor = payload.next;
  };

  AnchorTerm.prototype._setStatus = function (st) {
    if (!st) return;
    this.status = st;
    if (this._statusEl) this._statusEl.textContent = st;
    if (this._dot) {
      this._dot.className = "dot" +
        (st === "running" || st === "awaiting-input" ? " live" :
         (st === "done" ? " done" : (st === "failed" || st === "cancelled" || st === "interrupted" ? " fail" : "")));
    }
  };

  AnchorTerm.prototype._renderGate = function (prompt) {
    this.pending = prompt;
    var g = el("div", "aterm-gate");
    var q = el("div", "q"); q.textContent = prompt && prompt.question ? prompt.question : "Input requested";
    g.appendChild(q);
    var opts = el("div", "opts");
    var list = (prompt && prompt.options) || [];
    var self = this;
    list.forEach(function (o) {
      var label = (o && o.label != null) ? o.label : String(o);
      var b = el("button", "opt");        // value set via DOM, never string-concatenated into HTML
      b.textContent = label;
      b.addEventListener("click", function () { self.sendTurn(label); });
      opts.appendChild(b);
    });
    g.appendChild(opts);
    this._screen.appendChild(g);
    this._screen.scrollTop = this._screen.scrollHeight;
  };

  // POST one turn to the live session stdin (token-aware via the caller's helper).
  AnchorTerm.prototype.sendTurn = function (text) {
    text = (text || "").trim();
    if (!text || this.closed) return;
    this.writeLine("› " + text, "user");
    this.pending = null;
    var self = this;
    var payload = { session: this.sessionId, text: text };
    Promise.resolve(this.postJson("/api/rnd/term_input", payload))
      .then(function (data) {
        if (!data || !data.ok) {
          self.writeLine("[input refused: " + ((data && (data.error || data.reason)) || "unknown") + "]", "error");
        }
      })
      .catch(function (e) { self.writeLine("[input error] " + e.message, "error"); });
  };

  // Start consuming the SSE stream. The endpoint heartbeats + terminates cleanly,
  // so on a benign close we re-open while the session is still live.
  AnchorTerm.prototype.start = function () {
    if (this.closed) return;
    var self = this;
    var url = "/api/rnd/term_stream?session=" + encodeURIComponent(this.sessionId) +
              "&since=" + encodeURIComponent(this.cursor);
    var es = new EventSource(url);
    this._es = es;
    es.addEventListener("output", function (ev) {
      try { self._renderOutput(JSON.parse(ev.data)); } catch (e) {}
    });
    es.addEventListener("status", function (ev) {
      try { self._setStatus(JSON.parse(ev.data).status); } catch (e) {}
    });
    es.addEventListener("gate", function (ev) {
      try { self._renderGate(JSON.parse(ev.data).prompt); } catch (e) {}
    });
    es.addEventListener("done", function (ev) {
      try { self._setStatus(JSON.parse(ev.data).status); } catch (e) {}
      es.close();
      self._es = null;
      self._onExit();
    });
    es.addEventListener("heartbeat", function () { /* keep-alive; stream may end after */ });
    es.onerror = function () {
      // The stream ended (bounded/heartbeat design). Re-open if the session is
      // still live; otherwise fall to the exit path.
      es.close();
      self._es = null;
      var terminal = ["done", "cancelled", "interrupted", "failed"];
      if (!self.closed && terminal.indexOf(self.status) < 0) {
        setTimeout(function () { self.start(); }, 400);
      } else {
        self._onExit();
      }
    };
  };

  // On exit: ask the server what the session produced and offer confirm-adopt.
  AnchorTerm.prototype._onExit = function () {
    if (this.closed) return;
    this.closed = true;
    if (this._input) { this._input.disabled = true; this._input.setAttribute("placeholder", "session ended"); }
    var self = this;
    Promise.resolve(this.postJson("/api/rnd/term_discover", { session: this.sessionId }))
      .then(function (data) {
        if (data && data.ok && data.proposal && data.proposal.adoptable) {
          self._renderAdopt(data.proposal);
        } else {
          self.writeLine("[session ended — no produced files to adopt]", "system");
        }
      })
      .catch(function (e) { self.writeLine("[discover error] " + e.message, "error"); });
  };

  AnchorTerm.prototype._renderAdopt = function (proposal) {
    var panel = el("div", "aterm-adopt");
    var h = el("h5"); h.textContent = "Session produced " + proposal.produced.length + " file(s) — adopt as a " +
      (proposal.lane || "") + " session?";
    panel.appendChild(h);
    var ul = el("ul");
    proposal.produced.forEach(function (p) {
      var li = el("li"); li.textContent = p.rel + (p.kind ? "  (" + p.kind + ")" : ""); ul.appendChild(li);
    });
    panel.appendChild(ul);
    var row = el("div", "row");
    var yes = el("button", "accent"); yes.textContent = "Adopt as session";
    var no = el("button"); no.textContent = "Dismiss";
    var self = this;
    yes.addEventListener("click", function () {
      Promise.resolve(self.postJson("/api/rnd/term_adopt", { session: self.sessionId }))
        .then(function (data) {
          if (data && data.ok) {
            panel.innerHTML = "<h5>Adopted as a session ✓</h5>";
            self._adopted = true;       // do not reap an adopted session on unload
            self.onAdopted(data);
          } else {
            self.writeLine("[adopt refused: " + ((data && data.error) || "unknown") + "]", "error");
          }
        })
        .catch(function (e) { self.writeLine("[adopt error] " + e.message, "error"); });
    });
    no.addEventListener("click", function () { panel.parentNode && panel.parentNode.removeChild(panel); });
    row.appendChild(yes); row.appendChild(no);
    panel.appendChild(row);
    this.host.querySelector(".aterm").appendChild(panel);
  };

  // Best-effort cancel of the live session's persistent process. Used on tab
  // close / dispose when the session is still live and was NOT yet adopted — a
  // persistent stream-json REPL otherwise waits for input forever (a leak). The
  // cancel POST carries the token in the JSON BODY (the server's auth middleware
  // accepts a "token" field) because sendBeacon / unload requests can't set the
  // X-Anchor-Token header. Prefers navigator.sendBeacon (survives unload), falls
  // back to a keepalive fetch, then a sync XHR — whichever lands.
  AnchorTerm.prototype._reapCancel = function () {
    if (this._reaped) return;
    this._reaped = true;
    var sid = this.sessionId;
    if (!sid) return;
    var token = "";
    try { token = localStorage.getItem("anchor_token") || ""; } catch (e) {}
    var payload = { job_id: sid };
    if (token) payload.token = token;
    var bodyStr = JSON.stringify(payload);
    var url = "/api/rnd/cancel_job";
    try {
      if (navigator && typeof navigator.sendBeacon === "function") {
        var blob = new Blob([bodyStr], { type: "application/json" });
        if (navigator.sendBeacon(url, blob)) return;
      }
    } catch (e) {}
    try {
      if (typeof fetch === "function") {
        fetch(url, { method: "POST", body: bodyStr, keepalive: true,
                     headers: { "Content-Type": "application/json" } });
        return;
      }
    } catch (e) {}
    try {
      var xhr = new XMLHttpRequest();
      xhr.open("POST", url, false);            // sync fallback so it lands on unload
      xhr.setRequestHeader("Content-Type", "application/json");
      xhr.send(bodyStr);
    } catch (e) {}
  };

  AnchorTerm.prototype.dispose = function () {
    // If the session is still live and was not adopted/finished, fire a
    // best-effort cancel so the abandoned persistent process is reaped.
    var live = !this.closed &&
      ["done", "cancelled", "interrupted", "failed"].indexOf(this.status) < 0;
    this.closed = true;
    if (this._beforeUnload) {
      try { window.removeEventListener("beforeunload", this._beforeUnload); } catch (e) {}
      this._beforeUnload = null;
    }
    if (live && !this._adopted) this._reapCancel();
    if (this._es) { try { this._es.close(); } catch (e) {} this._es = null; }
  };

  // Public factory. Swap-point: replace the AnchorTerm body with an xterm.js
  // adapter here and callers (anchor_gui project window) need not change.
  window.AnchorTerm = {
    mount: function (opts) {
      var t = new AnchorTerm(opts);
      // Reap the abandoned persistent process if the user closes the tab while
      // the session is still live and unadopted (best-effort cancel on unload).
      t._beforeUnload = function () {
        var live = !t.closed &&
          ["done", "cancelled", "interrupted", "failed"].indexOf(t.status) < 0;
        if (live && !t._adopted) t._reapCancel();
      };
      try { window.addEventListener("beforeunload", t._beforeUnload); } catch (e) {}
      t.start();
      return t;
    }
  };
})();
