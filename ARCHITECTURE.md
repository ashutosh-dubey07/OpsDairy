# OpsDiary architecture

OpsDiary is a local-first, voice-led incident capture demo for Hinglish-speaking on-call engineers. All bundled records and examples are synthetic. The app does not predict outages or execute remediation.

## Request flow

```text
Streamlit capture/review
  -> Prisma adapter (explicit Live action only)
  -> IncidentWorkflow
  -> Pydantic validation and human review
  -> SQLite incident store
  -> service/deployment enrichment
  -> exact historical pattern checks + FTS5 incident/runbook retrieval
  -> evidence-backed report and optional Timbre speech
```

## Implemented layers

| Layer | Implementation | Trust boundary |
| --- | --- | --- |
| UI and input | Streamlit Demo/Live flows; transcript fields are reviewed before saving | Live mode requires credentials and a deliberate button click |
| Provider adapter | Prisma v2.5 STT and Timbre v2.5 TTS in `opsdiary/gnani_client.py` | Keys come from environment; audio remains in session memory |
| Application workflow | `IncidentWorkflow` owns extraction, save validation, enrichment, retrieval, and report assembly | UI delegates incident mutations and analysis to the workflow |
| Incident schema | Pydantic fields, known-service/symptom checks, transcript evidence, trace ID | Unknown fields stay unset; the operator confirms candidate values |
| Review feedback | SQLite stores extracted candidates, confirmed values, and changed fields; `opsdiary.feedback` summarizes local correction rates | Corrections are an audit/evaluation signal; the report omits transcript text and does not train extraction |
| Context | Service catalog and exact deployment-version match from SQLite | A latest deployment is labeled as context, not as incident cause |
| Retrieval | Exact service/environment/symptom matching plus SQLite FTS5 search over incidents and bundled runbook examples | Results include incident IDs or runbook IDs, matched terms, and source evidence; runbooks require a confirmed service |
| Persistence | SQLite incidents, services, deployments, synthetic runbooks, and FTS indexes | Seed records are synthetic; raw audio is not stored |
| Operations | Structured stage logs include trace ID, provider, outcome, latency, request ID, and error type | Logs omit transcript text, audio content, API keys, and exception messages |
| Quality | Mocked provider contract checks, workflow tests, synthetic extraction evaluation, CI | CI uses no credentials and makes no live provider calls |

## Deliberate scope

The current demo is single-user and has no write actions into external systems. Team-level RBAC and MCP tool servers belong with a multi-user deployment or an actual service connector. A cache is unnecessary for the current small local dataset. Extraction and analysis use deterministic code, so a generative system prompt and prompt-injection classifier are not part of this path. Runbook records are synthetic examples, not operational guidance. Semantic retrieval should be evaluated against real, permission-safe examples before adding a vector index; FTS5 is the current lexical baseline.

The next integration should be chosen from the challenge demo's available evidence sources. Any external write action must be previewed and explicitly confirmed by the engineer.
