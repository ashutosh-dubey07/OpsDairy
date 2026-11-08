# OpsDiary architecture

OpsDiary is a local-first, voice-led incident capture demo for Hinglish-speaking on-call engineers. All bundled records and examples are synthetic. The app does not predict outages or execute remediation.

## Request flow

```text
Loopback-only Streamlit sign-in (local account)
  -> deterministic Ask FAQs or SQLite FTS5 evidence search
  -> saved query/answer audit record scoped to the signed-in account
  -> authenticated incident capture/review
  -> Prisma adapter (explicit Live action only)
  -> IncidentWorkflow
  -> Pydantic validation and human review
  -> SQLite incident store
  -> service/deployment enrichment
  -> exact historical pattern checks + FTS5 incident/runbook retrieval
  -> local incident timeline (update, mitigated, resolved)
  -> evidence-backed report and optional Timbre speech
```

## Implemented layers

| Layer | Implementation | Trust boundary |
| --- | --- | --- |
| Local access | One-time first-run registration; Argon2id password hashes; parameterized username queries; login and recovery throttling; idle and absolute session expiry; password reset revokes sessions | Recovery code is generated once, stored as a verifier, consumed and rotated on reset; local terminal reset is the fallback; Streamlit binds to loopback |
| Ask assistant | Exact local FAQ rules for common greetings/product questions; lexical incident search through SQLite FTS5; query, answer, intent, trace ID, actor and evidence references persisted | No LLM/STT/TTS calls; no-match replies are explicit; every submitted exchange is stored in local SQLite |
| UI and input | Streamlit Demo/Live flows; transcript fields are reviewed before saving | Live mode requires credentials and a deliberate button click |
| Provider adapter | Prisma v2.5 STT and Timbre v2.5 TTS in `opsdiary/gnani_client.py` | Keys come from environment; audio remains in session memory |
| Application workflow | `IncidentWorkflow` owns extraction, save validation, enrichment, retrieval, timeline updates, and report assembly | UI delegates incident mutations and analysis to the workflow |
| Incident schema | Pydantic fields, known-service/symptom checks, transcript evidence, trace ID | Unknown fields stay unset; the operator confirms candidate values |
| Review feedback | SQLite stores extracted candidates, confirmed values, and changed fields; `opsdiary.feedback` summarizes local correction rates | Corrections are an audit/evaluation signal; the report omits transcript text and does not train extraction |
| Context | Service catalog and exact deployment-version match from SQLite | A latest deployment is labeled as context, not as incident cause |
| Retrieval | Exact service/environment/symptom matching plus SQLite FTS5 search over incidents and bundled runbook examples | Results include incident IDs or runbook IDs, matched terms, and source evidence; runbooks require a confirmed service |
| Persistence | SQLite local account/recovery verifiers, throttling state, Ask exchanges, incidents, services, deployments, synthetic runbooks, timeline events, and FTS indexes | Account passwords and raw recovery codes are not stored in plaintext; Ask content is retained locally; seed records are synthetic; raw audio is not stored; the SQLite file itself is not encrypted |
| Operations | Structured stage logs include trace ID, provider, outcome, latency, request ID, and error type | Logs omit transcript text, audio content, API keys, and exception messages |
| Quality | Mocked provider contract checks, workflow tests, synthetic extraction evaluation and operator correction summary in the dashboard, CI | CI uses no credentials and makes no live provider calls; evaluation uses only synthetic cases |

## Deliberate scope

The current demo is a local single-operator application with no write actions into external systems. Its initial local registration and recovery-code flow do not provide multi-user identity, MFA, encrypted database storage, email recovery, or a network deployment security boundary. Do not expose the Streamlit process directly to a network. Team-level RBAC and MCP tool servers belong with a multi-user deployment or an actual service connector. A cache is unnecessary for the current small local dataset. Extraction and analysis use deterministic code, so a generative system prompt and prompt-injection classifier are not part of this path. Runbook records are synthetic examples, not operational guidance. Semantic retrieval should be evaluated against real, permission-safe examples before adding a vector index; FTS5 is the current lexical baseline.

The next integration should be chosen from the challenge demo's available evidence sources. Any external write action must be previewed and explicitly confirmed by the engineer.
