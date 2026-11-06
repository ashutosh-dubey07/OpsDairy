# OpsDiary

OpsDiary keeps incident notes, service context, and related history together for Hinglish-speaking SRE and on-call engineers. Demo records are synthetic. The app does not predict outages and is not production software.

## Run locally

Requirements: Python 3.12 and `uv`.

```powershell
uv venv .venv --python 3.12
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
streamlit run app.py
```

On first run, the app creates `data/opsdiary.sqlite3` and loads the synthetic seed files. That database is ignored by Git. To restore the original seed set, stop the app and remove the local database.

## Demo mode

Demo is the default and remains available without credentials. **Run sample incident** saves the built-in synthetic transcript and shows enrichment and historical matches in one step; it reuses the existing matching sample instead of creating duplicates. For the manual path, edit a synthetic Hinglish transcript, extract candidate fields, review them, and save. No audio is recorded or sent in Demo. History can be searched, and a selected incident can be downloaded as a Markdown brief with supporting records.

## Live mode

Live mode is available only when `GNANI_API_KEY` is configured. Without a key, the mode selector stays on Demo and shows a short setup note. Importing the API module or loading the page does not make a request.

1. Copy `.env.example` to `.env` and set `GNANI_API_KEY` to a Gnani key authorized for both STT and TTS. Keep `.env` local; it is ignored by Git.
2. Restart Streamlit so the environment is reloaded.
3. Select **Live**, record a synthetic note with the microphone or upload a synthetic WAV clip no longer than 30 seconds, then press **Transcribe audio**.
4. Review/edit the transcript, choose **Extract fields**, review the structured fields, and save.
5. Press **Speak summary** to call Timbre v2.5 and play the returned WAV audio.

Audio inputs are kept in Streamlit session memory for the request and are not written to disk. The Live upload flow accepts WAV so the app can enforce the 30-second duration locally before sending. Use synthetic audio/text only; do not upload production recordings or customer data.

Optional app configuration (the defaults are shown):

```dotenv
GNANI_API_KEY=<your Gnani API key>
GNANI_STT_LANGUAGE_CODE=hi-IN
GNANI_TTS_VOICE=Poorvi
GNANI_TTS_LANGUAGE=hi-en
```

The client uses Prisma v2.5 REST at `https://api.vachana.ai/stt/v3`; it sends `audio_file` and required `language_code`, omitting `model` because Prisma v2.5 is the documented default. Timbre v2.5 uses `https://api.vachana.ai/api/v1/tts/inference` and requests WAV audio. Both use the `X-API-Key-ID` authentication header. The UI calls them only from the explicit Transcribe and Speak buttons.

## Application workflow and quality gates

The Streamlit page calls `IncidentWorkflow` for extraction, reviewed-field validation, persistence, and incident analysis. This keeps application rules independent of UI rendering. Unknown service IDs and symptom tags are rejected before persistence.

Run the synthetic extraction evaluation locally:

```powershell
.\.venv\Scripts\python.exe -m opsdiary.evaluation
```

The evaluation uses only `data/evaluation_cases.json` and the synthetic service catalog. It checks exact field accuracy and evidence presence; every field gate must reach 90% and evidence coverage must reach 95%. It makes no API calls.

The GitHub Actions workflow in `.github/workflows/ci.yml` installs the existing requirements, runs the unit and mocked API checks, then runs the synthetic evaluation on pushes and pull requests. It does not deploy the app or need API credentials. It will start running after this folder is added to a GitHub repository.

## Mocked API contract checks

Run without credentials or network access:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The tests mock `requests.post`; they check the STT multipart fields, TTS JSON payload and WAV response handling, missing-key behavior, and the 30-second WAV limit. They do not call Gnani.
