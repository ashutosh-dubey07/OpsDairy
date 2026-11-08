# OpsDiary

OpsDiary keeps incident notes, service context, and related history together for Hinglish-speaking SRE and on-call engineers. Demo records are synthetic. The app does not predict outages and is not production software.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the layer map, trust boundaries, and current scope decisions.

## Run locally

Requirements: Python 3.12 and `uv`.
Direct runtime dependencies are pinned in `requirements.txt` to keep CI and local installs aligned.

```powershell
uv venv .venv --python 3.12
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
.\.venv\Scripts\streamlit.exe run app.py
```

On first run, the app creates `data/opsdiary.sqlite3` and loads the synthetic seed files. That database is ignored by Git. Set `OPSDIARY_DATABASE_PATH` to a persistent path when the default project data folder is unsuitable. To restore the original seed set, stop the app and remove the local database.

## Demo mode

Demo is the default and remains available without credentials. **Run sample incident** saves the built-in synthetic transcript and shows enrichment and historical matches in one step; it reuses the existing matching sample instead of creating duplicates. For the manual path, edit a synthetic Hinglish transcript, extract candidate fields, review them, and save. A deployment version from the transcript is linked only when the service, environment, and exact version match the synthetic catalog. The latest catalog deployment is shown separately as context, without claiming it caused the incident. No audio is recorded or sent in Demo. History can be searched, and a selected incident can be downloaded as a Markdown brief with supporting records.

## Live mode

Live mode is available only when `GNANI_API_KEY` is configured. Without a key, the mode selector stays on Demo and shows a short setup note. Importing the API module or loading the page does not make a request.

1. Create a file named `.env` in the project root and add `GNANI_API_KEY=<your Gnani API key>`. Add the optional settings below only if you need to override their defaults. Keep `.env` local; it is ignored by Git.
2. Restart Streamlit so the environment is reloaded.
3. Select **Live**, record a synthetic note with the microphone or upload a synthetic WAV clip no longer than 30 seconds, then press **Transcribe audio**.
4. Review/edit the transcript, choose **Extract fields**, review the structured fields, and save.
5. Press **Speak summary** to call Timbre v2.5 and play the returned WAV audio.
6. In the saved incident or History, add a text update or record/upload a synthetic WAV clip up to 30 seconds. Transcribe explicitly, review the text, select Update/Mitigated/Resolved, then save it to the incident timeline.

Audio inputs are kept in Streamlit session memory for the request and are not written to disk. Live STT accepts WAV clips up to 30 seconds and 10 MB; the server rejects larger uploads and the client checks both limits before sending. Use synthetic audio/text only; do not upload production recordings or customer data.

Each explicit **Transcribe audio**, **Transcribe update**, or **Speak summary** action sends one request to Gnani and may consume account credits. Demo mode, page loads, and mocked tests make no Gnani calls.

Timeline entries are stored locally with UTC time, event type, source, and trace ID. They are engineer-authored notes; they do not trigger external actions or change infrastructure state.

Optional app configuration (the defaults are shown):

```dotenv
GNANI_API_KEY=<your Gnani API key>
GNANI_STT_LANGUAGE_CODE=hi-IN
GNANI_TTS_VOICE=Poorvi
GNANI_TTS_LANGUAGE=hi-en
OPSDIARY_DATABASE_PATH=data/opsdiary.sqlite3
```

The client uses Prisma v2.5 REST at `https://api.vachana.ai/stt/v3`; it sends `audio_file` and required `language_code`, omitting `model` because Prisma v2.5 is the documented default. Timbre v2.5 uses `https://api.vachana.ai/api/v1/tts/inference` and requests WAV audio. Both use the `X-API-Key-ID` authentication header. The UI calls them only from the explicit Transcribe and Speak buttons.

## Application workflow and quality gates

The Streamlit page calls `IncidentWorkflow` for extraction, reviewed-field validation, persistence, and incident analysis. This keeps application rules independent of UI rendering. Unknown service IDs and symptom tags are rejected before persistence.

Each saved incident keeps its extracted candidate fields alongside the values confirmed by the operator. Changed fields appear in the incident view and Markdown report, providing a review trail for later extractor evaluation. This feedback is stored locally and does not train or modify the extractor automatically.

Historical context uses SQLite FTS5 lexical retrieval, filtered by confirmed service and environment when available. Results include the source incident ID, matched terms, and transcript evidence excerpt. The same retrieval layer can show bundled synthetic runbook examples only for the confirmed service; each result carries its runbook ID and matching terms. These checklists are illustrative examples, not approved operational instructions, and must be checked against the service's real runbook. Structured JSON operational logs record trace ID, stage, outcome, latency, and provider metadata; they omit transcript text, audio bytes, and API keys.

Run the synthetic extraction evaluation locally:

```powershell
.\.venv\Scripts\python.exe -m opsdiary.evaluation
```

The Evaluation tab and CLI use only `data/evaluation_cases.json` and the synthetic service catalog. They check exact field accuracy and evidence presence; every field gate must reach 90% and evidence coverage must reach 95%. The test set includes negated/resolved symptoms and corrected severity, environment, and deployment mentions. Results are synthetic checks, not a claim of real-world accuracy, and make no API calls. The tab also shows operator correction counts without treating them as accuracy or training data.

Summarize saved operator corrections locally:

```powershell
.\.venv\Scripts\python.exe -m opsdiary.feedback
```

This prints per-field review counts and correction rates without transcript text. These rates are review signals, not accuracy metrics; they do not train the extractor.

The GitHub Actions workflow in `.github/workflows/ci.yml` installs the existing requirements, runs the unit and mocked API checks, then runs the synthetic evaluation on pushes and pull requests. It does not deploy the app or need API credentials.

## Mocked API contract checks

Run without credentials or network access:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests mock `requests.post`; they check the STT multipart fields, TTS JSON payload and WAV response handling, missing-key behavior, and the 30-second WAV limit. They do not call Gnani.
