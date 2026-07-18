#!/usr/bin/env node
// agy_job_adapter.mjs — Anchor job_runner's Gemini transport shim.
//
// This host has NO bare `gemini` CLI; Gemini IS the `agy` CLI, and the sanctioned
// wrapper is agy-dispatch.mjs (it applies the no-shell STEER, polls the agy
// conversation transcript, and hides the window). But job_runner captures a
// child's STDOUT and parses stream-json envelopes, while agy-dispatch writes the
// model reply to a --out FILE (nothing usable on stdout). This thin shim bridges
// the two: it runs agy-dispatch, reads the reply file, and re-emits the reply as
// exactly ONE stream-json `result` line on stdout, so
// job_runner.extract_assistant_text (and gandalf._map_shards / summarizer) parse
// it unchanged.
//
// Invoked by job_runner._build_gemini_argv as:
//   node agy_job_adapter.mjs --prompt-file <f> --model <m> [--readonly] --target <dir>

import { spawnSync } from 'node:child_process';
import { readFileSync, mkdtempSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const isMain = process.argv[1] && process.argv[1] === fileURLToPath(import.meta.url);

if (isMain) {
  const argVal = (flag) => {
    const i = process.argv.indexOf(flag);
    return i >= 0 && i + 1 < process.argv.length ? process.argv[i + 1] : null;
  };
  const hasFlag = (flag) => process.argv.includes(flag);

  const emit = (text) =>
    process.stdout.write(JSON.stringify({ type: 'result', result: String(text || '') }) + '\n');

  const promptFile = argVal('--prompt-file');
  const model = argVal('--model') || process.env.GEMINI_MODEL || 'gemini-3.1-pro';
  const target = argVal('--target') || process.cwd();
  const readonly = hasFlag('--readonly');

  const DISPATCH =
    process.env.ANCHOR_AGY_DISPATCH || 'C:\\dev\\Skill Foundry\\tools\\agy-dispatch.mjs';

  if (!promptFile) {
    process.stderr.write('agy_job_adapter: --prompt-file required\n');
    emit('');
    process.exit(2);
  }

  const outFile = path.join(mkdtempSync(path.join(os.tmpdir(), 'agyjob-')), 'reply.txt');

  const args = [DISPATCH, '--prompt-file', promptFile, '--target', target, '--out', outFile, '--model', model, '--json-safe'];
  if (readonly) args.push('--readonly');

  // agy-dispatch prints its OWN one-line JSON status to stdout; that must NOT leak
  // into our stdout (job_runner captures it). Route the child's stdout to OUR
  // stderr (fd 2 — folded into the job log, ignored by extract_assistant_text).
  const r = spawnSync('node', args, { stdio: ['ignore', 2, 'inherit'], windowsHide: true });

  let text = '';
  try { text = readFileSync(outFile, 'utf8'); } catch { /* no reply produced */ }

  // agy's transcript reconstruction can leave stray RAW control chars inside the
  // model's text (observed: a raw newline at ~2KB streaming boundaries) that break
  // strict JSON parsing downstream (gandalf's _last_balanced_json -> json.loads).
  // The model escapes its OWN intended newlines as \n (two chars), so any raw byte
  // with code < 32 here is a structural/artifact char, safe to flatten to a space —
  // keeps a JSON draft valid without altering escaped string content.
  text = Array.from(text, (ch) => (ch.charCodeAt(0) < 32 ? ' ' : ch)).join('');

  emit(text);
  // Exit 0 when we got a real reply so job_runner marks the job DONE (gandalf skips
  // non-done shards). If agy produced nothing, fail honestly with the child's code.
  process.exit(text && text.trim() ? 0 : (r.status || 1));
}