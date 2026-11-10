# OpsDiary architecture

OpsDiary is a local-first, voice-led incident capture and history tool for Hinglish-speaking SRE and on-call engineers. Incident audio and bundled records are synthetic in this MVP. OpsDiary does not predict outages, identify root cause, or execute remediation.

## Request flow

```text
Loopback-only Streamlit application
  -> first-run local registration or sign-in
  -> explicit microphone recording or WAV upload
  -> explicit Prisma v2.5 transcription request
  -> transcript review and edit
  -> deterministic extraction of candidate incident fields
  -> operator review and edit
  -> Pydantic validation and SQLite save
  -> service and deployment context enrichment
  -> historical pattern matches and SQLite FTS5 evidence retrieval
  -> timeline and Markdown incident report
  -> optional, explicit Timbre v2.5 summary speech

Ask tab
  -> fixed local FAQ rules
  -> otherwise SQLite FTS5 search of saved incidents
  -> answer and evidence references saved in SQLite
```

## Implemented layers

| Layer | Implementation | Boundary |
| --- | --- | --- |
| Local access | One local account, Argon2id password hashes, parameterized SQLite queries, persistent login throttling, one-time recovery code, idle and absolute session expiry | No team accounts, MFA, hosted identity, or email recovery. The recovery code is shown once; only its verifier is stored. |
| Presentation | Streamlit pages for incident capture, history, Ask, and synthetic evaluation | The app binds to loopback. Loading or rendering a page does not call Gnani. |
| Voice input | Microphone recording or WAV upload, limited to 30 seconds and 10 MB | Audio stays in request/session memory and is not written to disk by OpsDiary. Only an explicit button sends it to Gnani. |
| Provider adapter | Prisma v2.5 REST transcription and Timbre v2.5 REST speech in `opsdiary/gnani_client.py` | `GNANI_API_KEY` is read from the process environment or ignored `.env`. Requests use documented endpoints and payloads. |
| Incident workflow | `IncidentWorkflow` coordinates rule-based extraction, validation, save, enrichment, retrieval, timeline, and report assembly | Extracted values remain candidates until the engineer reviews and saves them. |
| Incident schema | Pydantic model constrains fields, transcript evidence, service identifiers, severity, symptoms, and environment | Unsupported or invalid values fail validation before persistence. |
| Context and retrieval | Local service/deployment catalog, exact version matching, deterministic service/environment/symptom matching, SQLite FTS5 incident and runbook search | Deployment context is not evidence of causation. Search matches include supporting records; similarity is not a shared-cause claim. |
| Ask | Fixed answers for greetings and common questions; local FTS5 search for other queries | Ask does not call an LLM, Prisma, or Timbre. Every submitted question and answer is stored locally, scoped to the signed-in account. |
| Persistence | SQLite stores incidents, review audit data, service and deployment fixtures, timeline events, runbooks, Ask exchanges, authentication state, and FTS indexes | Bundled records are synthetic. The database is local and is not encrypted by the app. |
| Observability | Structured stage logs include trace ID, outcome, latency, request ID, and byte counts | Logs omit transcripts, audio bytes, passwords, API keys, and provider exception text. |
| Quality | Unit/workflow tests, mocked provider-contract tests, concurrent SQLite regression, synthetic extraction evaluation, Ruff, and CI dependency audit | One live synthetic TTS-to-STT smoke check confirms basic connectivity only; it does not prove recognition accuracy, provider capacity, or production readiness. |

## Client scale and delivery boundary

Current operation is intentionally one local account, one Streamlit process, one SQLite file, and loopback-only access. The synthetic storage check measured 600 mixed SQLite operations with 24 worker threads and no database errors; it is a local storage datapoint, not a supported concurrent-user target. SQLite still serializes writes, and the data model does not enforce tenant boundaries.

Do not scale this deployment by adding Streamlit replicas or placing the SQLite file on shared storage. A team rollout needs these changes in order:

1. Add OIDC login, roles, tenant IDs, and authorization checks at every workflow and database boundary. Enforce tenant ownership in SQL and PostgreSQL row-level policies; test cross-tenant isolation.
2. Move operational records to PostgreSQL, add versioned migrations, connection pooling, backups, restore drills, retention, and encryption at rest.
3. Put a stateless API behind a TLS-terminating reverse proxy. Keep Streamlit as an internal UI only if its session model fits the deployment.
4. Isolate Prisma/Timbre calls behind bounded workers. Apply per-tenant concurrency/rate limits, explicit credit budgets, deadlines, idempotency keys, and back-pressure. Do not automatically retry billable requests. Audio remains in memory and is not put on a durable queue.
5. Observe request rates, queue depth, p50/p95 latency, failures, and provider spend without logging transcripts, audio, passwords, or keys.

The current CI pipeline runs Ruff, a dependency vulnerability audit, the unit/UI and mocked-provider suite, and synthetic extraction gates on pushes and pull requests. The concurrent SQLite regression is part of the unit suite. There is no CD workflow because no hosting target, identity provider, TLS domain, secret manager, or backup environment has been approved and configured. Once a target exists, add staging deployment, migration checks, smoke tests, health monitoring, manual promotion, and rollback.

## Scope and operational limits

This is a single-operator local MVP, not a production deployment. Do not use production incident data, customer information, or production credentials. Do not expose the Streamlit process to a network. Protect the Windows account and local SQLite file; the app does not encrypt database contents or define a retention/deletion policy.

The service catalog, runbooks, incidents, and evaluation transcripts are synthetic. Runbook examples are not approved operational instructions. Historical pattern matching and FTS5 retrieval are deterministic evidence lookup, not outage prediction or automated diagnosis. FTS5 is the current retrieval baseline; add an external vector store or service connector only if a validated use case requires it.

All current integrations are read-only or local. Any future external write action must show its target and payload and require an explicit operator confirmation before submission.
