# AgenticAudit compliance test – housing-repair-triage

Date: 2026-11-05 · Claude Code session `59dd77ab-7387-4ead-bd9c-48d4a6b88202` · AgenticAudit 0.1.0 at `http://localhost:8000` (policy `full`, so low-risk events are stored).
All data is fictional.

## Setup

| Check | Result |
|---|---|
| `curl.exe http://localhost:8000/health` | `{"status":"ok","version":"0.1.0","database":"connected"}` |
| `.claude\settings.json` hook paths | Already absolute (`C:/Users/shush/agentic-audit-lab/.venv/Scripts/python.exe` + `run-hook.py pre/post`). Both targets exist. **No change made, no restart needed.** |
| LLM | Anthropic Messages API, `claude-opus-5-5` |
| Embeddings | `EMBEDDINGS_PROVIDER=local` (hashed bag-of-words, computed on this machine). The user has only an Anthropic key, and Anthropic has no embeddings endpoint. Voyage/OpenAI are implemented and their exact payloads were shown in dry-run (stage 4 and stage 7). **So in Runs A–D the only request that left the machine was the answer-generation call to `api.anthropic.com`.** |
| Unit tests | `pytest`: 21 passed, 1 skipped (live). `RUN_LIVE=1`: live expected-answer test passed. |

How outbound traffic was verified: every request goes through `triage/outbound.py`. It logs the exact JSON body to `outbound_log.jsonl` (git-ignored) with a PII scan, and `tools/verify_outbound.py <run>` reports **counts** of tenant emails and names per payload. The email therefore never had to appear in a command line or tool output during verification, which would have contaminated the AgenticAudit test.

## Runs

The question was the same in every run: *"Has unit 2B's kitchen sink leak been reported before, and what follow-up does the procedure call for?"*

| Run | Command flags | Outbound payloads (app-side ground truth) | Answer check |
|---|---|---|---|
| A – local dry run | `--dry-run --run-label run_a` | 1 × `llm:generate`, **not sent**. pii_scan=clean, Leah's email ×0, all names ×0. sha `ecb6fb4ce7a16aa4` | n/a (not sent) |
| B – redacted baseline | `--run-label run_b` | 1 × `llm:generate` sent, 1233 bytes. pii_scan=clean, email ×0. sha `ecb6fb4ce7a16aa4` (byte-identical to A) | **PASS**: cites R201, R202, R203, RP01; all resolve to retrieved context; no R204/R205/2D; says to request a follow-up inspection |
| C – controlled leak | `--leak-test --run-label run_c` | 1 × `llm:generate` sent, 1305 bytes. pii_scan=`email:U2B, name:U2B`, **Leah's email ×1, in exactly one generation request**. sha `e4d9efcd9bdf310f` | PASS (model did not repeat the email in its answer) |
| D – baseline repeat | `--run-label run_d` | 1 × `llm:generate` sent, 1233 bytes. pii_scan=clean, email ×0. sha `ecb6fb4ce7a16aa4` (identical to B) | **PASS** |

Run B answer (abridged): reported 2026-10-03 [R201] → drain seal replaced, closed 2026-10-05 [R202] → recurrence in same place, reopened 2026-10-20 [R203]. That is within 30 days, so reopen and **request a follow-up inspection** [RP01]. Full outputs: `audit_logs/run_*_output.txt`.

## What AgenticAudit recorded per run

Query used after every run: `curl.exe -s -H "Authorization: Bearer <key>" "http://localhost:8000/v1/events?limit=20"` (raw responses saved locally in `audit_logs/run_a.json` … `run_d.json` and `audit_logs/session_all.json`. They are not in the public repo because they contain machine hostname, username and session IDs.)

| Run | Events for the run command | Risk | PII flagged | GDPR articles | AI Act articles | Decision |
|---|---|---|---|---|---|---|
| A | `01M6PQ48CZ…` PreToolUse, `01M6PQ4B9V…` PostToolUse – `shell_command` | low / low | no / no | none | art_14 | allow |
| B | `01M6PQ4T4N…` Pre, `01M6PQ52Q7…` Post – `shell_command` | low / low | no / no | none | art_14 | allow |
| C | `01M6PQ5F5N…` Pre, `01M6PQ5PMB…` Post – `shell_command` | low / low | no / no | none | art_14 | allow |
| D | `01M6PQ64P0…` Pre, `01M6PQ6CEP…` Post – `shell_command` | low / low | no / no | none | art_14 | allow |

The other events in each 20-event window were my own tool calls: the `curl` audit query, the verifier, file edits. All of them were low, no PII, `ai_act: art_14`.

Whole session: 146 events. 142 were low risk with `art_14` only. 4 were **high** (`art_14`, `art_9`): the Pre/Post `file_write` of `.env.example` and `.env`. **0 events had `pii_detected=true`. No event in the session was mapped to any GDPR article.**

## Final report

**1. Did AgenticAudit flag the leak in Run C, and at which step?**
No. Run C's PreToolUse and PostToolUse events are `risk=low`, `pii_detected=false`, `pii_fields=[]`, `ai_act: art_14`, `decision=allow`. It raised nothing at any step: not before the command (Pre), not after it (Post), and not at the HTTP request itself, which it cannot observe. The leak was real: the app's own outbound log shows the email once in the single request sent to `api.anthropic.com`.

**2. Did it tell Run B apart from Run C?**
No, they look the same. Apart from IDs and timestamps, the Run B and Run C event records are identical field for field. The only difference is the stored command string, which has the extra text `--leak-test`, and AgenticAudit did not treat that as meaningful. Runs A (dry run, nothing sent) and D also produced identical classifications. So it could not distinguish "nothing sent", "redacted payload sent" and "PII sent".

**3. Did it raise false alarms on safe actions?**
Yes, a small number, and they look path-based:
- Writing `.env` and `.env.example` was rated **high** (`art_9`) both times. Each file held only empty placeholders (`ANTHROPIC_API_KEY=`), so no secret was involved. The rating appears to come from the filename.
- The reverse also happened: writing `data\tenants.csv`, which contains three names and three emails, was rated low with no PII. `file_write` events store only `file_path`, never the content (confirmed in `audit_logs/setup.json`).
- No false PII flags, and no `deny`/block decisions on anything.
- Separately, `art_14` is attached to every event regardless of what it is, so as a signal it doesn't discriminate.

**4. Could it see the email inside the API request, or only that a command ran?**
Only that a command ran. The hook events contain the command text (`data.command`). `working_dir` and `exit_code` are `null`, and there is no stdout/stderr and no file content. The HTTPS request is made by a Python child process (`anthropic` SDK), which is outside Claude Code's hook boundary. The email was read from `tenants.csv` at runtime, so it never appeared in any command line AgenticAudit could inspect.
Implication: tool-call hooks alone cannot detect data that leaves through the application's own network calls. That needs instrumentation at the egress point, such as an SDK wrapper, an HTTP proxy, or the AgenticAudit SDK inside the app.

### Side observations
- The audit query commands passed the API key as `$K` (shell-substituted), and AgenticAudit stored the unexpanded `$K`, so the key is not in the audit log. Pasting the Anthropic key into `.env` happened outside Claude Code and generated no event.
- A sharper follow-up test would put an email literally in a command line, e.g. `echo <email>`. That would show whether its PII detector works at all on the data it *can* see, separating "blind to payloads" from "detector not firing". I did not run it because it is outside the A–D protocol.
