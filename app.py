"""OpsDiary: minimal synthetic demo and explicitly triggered Gnani live mode."""

import streamlit as st

from opsdiary.extraction import SYMPTOM_LABELS
from opsdiary.gnani_client import (
    GnaniAPIError,
    GnaniConfigurationError,
    synthesize_timbre_v25,
    transcribe_prisma_v25,
    validate_wav_duration,
)
from opsdiary.observability import new_trace_id, observed_stage, trace_scope
from opsdiary.schema import IncidentDraft
from opsdiary.settings import GNANI_API_KEY
from opsdiary.workflow import IncidentWorkflow
from opsdiary.storage import (
    get_incident,
    init_db,
    list_incidents,
    list_services,
)

SAMPLE_TRANSCRIPT = (
    "Checkout API production mein deploy v2.8.1 ke baad 5xx errors aa rahe hain "
    "aur checkout slow chal raha hai; kuch users payments complete nahi paa rahe."
)
ENVIRONMENT_OPTIONS = ["production", "staging", "development"]
SEVERITY_OPTIONS = ["SEV1", "SEV2", "SEV3", "SEV4"]

st.set_page_config(page_title="OpsDiary", page_icon=None, layout="wide")
init_db()
services = list_services()
service_by_id = {item["service_id"]: item for item in services}
workflow = IncidentWorkflow(services)


def render_enrichment(result: dict | None) -> None:
    if not result:
        st.caption("No service catalog match.")
        return

    st.markdown("**Service**")
    st.write(
        f"{result['name']} - {result['service_id']} - {result['owner']} - "
        f"{result['criticality']} - {result['repository']}"
    )
    deployment_reference = result.get("deployment_reference")
    referenced = result.get("referenced_deployment")
    if deployment_reference:
        if referenced:
            st.markdown("**Transcript version match**")
            st.write(
                f"{referenced['version']} - {referenced['deployment_id']} - "
                f"commit {referenced['commit_sha']} - {referenced['deployed_at']} UTC"
            )
            st.caption(referenced["change_summary"])
        else:
            st.caption(
                f"Transcript mentions {deployment_reference}; no exact deployment version "
                "matches this service and environment in the catalog."
            )

    deployment = result.get("latest_deployment")
    if deployment and not (
        referenced and deployment["deployment_id"] == referenced["deployment_id"]
    ):
        st.markdown("**Latest catalog deployment**")
        st.write(
            f"{deployment['version']} - {deployment['environment']} - "
            f"{deployment['deployment_id']} - commit {deployment['commit_sha']} - "
            f"{deployment['deployed_at']} UTC"
        )
        st.caption(
            deployment["change_summary"]
            + " This is catalog context, not confirmation that it caused the incident."
        )
    elif deployment and referenced:
        st.caption("The verified transcript version is also the latest catalog deployment.")
    else:
        st.caption("No deployment is seeded for this service and environment.")


def render_pattern_evidence(result: dict) -> None:
    matches = result["matches"]
    if result["repeated"]:
        st.write(
            f"{len(matches)} prior incidents share this service, environment, and symptom "
            f"within {result['lookback_days']} days. Historical matches only; not a prediction."
        )
    elif matches:
        st.write(f"{len(matches)} prior match. Two or more are needed to show a repeated pattern.")
    else:
        st.write("No matching prior incidents.")

    for match in matches:
        tags = ", ".join(SYMPTOM_LABELS.get(tag, tag) for tag in match["matched_symptoms"])
        st.markdown(f"**{match['incident_id']}** - {match['created_at']} UTC - {tags}")
        st.caption(match["transcript"])
        if match.get("deployment_id"):
            st.caption(f"Deployment: {match['deployment_id']}")


def render_related_records(records: list[dict]) -> None:
    st.markdown("**Additional transcript matches**")
    if not records:
        st.caption("No additional lexical matches in saved incident transcripts.")
        return
    st.caption("Text search evidence only; a shared cause is not confirmed.")
    for record in records:
        terms = ", ".join(record.get("matched_terms", [])) or "text match"
        st.markdown(f"**{record['incident_id']}** - {record['created_at']} UTC - {terms}")
        st.caption(record.get("evidence_excerpt") or record["transcript"])
        if record.get("deployment_id"):
            st.caption(f"Catalog deployment: {record['deployment_id']}")


def render_speech_controls(incident: dict, summary: str, location: str) -> None:
    """TTS runs only after an explicit click and stays in session memory."""
    if not GNANI_API_KEY:
        return
    audio_state_key = f"tts_audio_{incident['incident_id']}"
    if st.button("Speak summary", key=f"speak_{location}_{incident['incident_id']}"):
        try:
            metadata: dict = {}
            trace_id = incident.get("extraction", {}).get("trace_id")
            with trace_scope(trace_id):
                with st.spinner("Generating speech..."):
                    with observed_stage(
                        "voice.tts",
                        incident_id=incident["incident_id"],
                        provider="gnani-timbre-v2.5",
                        metadata=metadata,
                    ):
                        audio_bytes = synthesize_timbre_v25(summary)
                        metadata["output_bytes"] = len(audio_bytes)
            st.session_state[audio_state_key] = audio_bytes
        except (GnaniAPIError, GnaniConfigurationError, ValueError) as exc:
            st.error(f"TTS request failed: {exc}")
    if audio_bytes := st.session_state.get(audio_state_key):
        st.audio(audio_bytes, format="audio/wav")


def render_report_download(incident: dict, report: str, location: str) -> None:
    st.download_button(
        "Download incident report",
        data=report,
        file_name=f"{incident['incident_id']}.md",
        mime="text/markdown",
        key=f"download_{location}_{incident['incident_id']}",
    )


def render_incident_result(incident_id: str, allow_tts: bool = False) -> None:
    analysis = workflow.analyze(incident_id)
    if not analysis:
        return
    incident = analysis.incident
    st.subheader("Incident")
    st.caption(f"{incident['incident_id']} - {incident['created_at']} UTC - {incident['source']}")
    st.write(incident["transcript"])
    service_name = service_by_id.get(incident.get("service_id"), {}).get("name", "Unknown")
    st.write(
        f"Service: {service_name} | Environment: {incident.get('environment') or 'unspecified'} | "
        f"Severity: {incident.get('severity') or 'unspecified'}"
    )
    symptom_names = [SYMPTOM_LABELS.get(tag, tag) for tag in incident.get("symptoms", [])]
    if symptom_names:
        st.caption("Symptoms: " + ", ".join(symptom_names))
    if incident.get("impact_summary"):
        st.write("Impact: " + incident["impact_summary"])
    if incident.get("deployment_reference"):
        st.caption("Transcript deployment reference: " + incident["deployment_reference"])

    render_enrichment(analysis.service_context)
    st.markdown("**Historical matches**")
    render_pattern_evidence(analysis.pattern_result)
    render_related_records(analysis.related_records)
    if allow_tts:
        render_speech_controls(incident, analysis.summary, "result")
    render_report_download(incident, analysis.report, "result")


def render_review_form(
    draft_data: dict,
    draft_state_key: str,
    widget_prefix: str,
    source: str,
) -> None:
    st.subheader("Review")
    evidence = draft_data.get("evidence", {})
    for field_name, excerpt in evidence.items():
        st.caption(f"{field_name.replace('_', ' ').title()}: {excerpt}")

    service_ids = ["", *[item["service_id"] for item in services]]
    candidate_service = draft_data.get("service_id") or ""
    service_index = service_ids.index(candidate_service) if candidate_service in service_ids else 0
    environment_options = ["Not identified", *ENVIRONMENT_OPTIONS]
    environment_value = draft_data.get("environment") or "Not identified"
    environment_index = environment_options.index(environment_value) if environment_value in environment_options else 0
    severity_options = ["Unspecified", *SEVERITY_OPTIONS]
    severity_value = draft_data.get("severity") or "Unspecified"
    severity_index = severity_options.index(severity_value) if severity_value in severity_options else 0

    with st.form(f"review_and_save_{widget_prefix}", border=False):
        selected_service = st.selectbox(
            "Service",
            service_ids,
            index=service_index,
            key=f"{widget_prefix}_service",
            format_func=lambda value: "Not identified" if not value else f"{service_by_id[value]['name']} ({value})",
        )
        selected_environment = st.selectbox(
            "Environment", environment_options, index=environment_index, key=f"{widget_prefix}_environment"
        )
        selected_severity = st.selectbox(
            "Severity", severity_options, index=severity_index, key=f"{widget_prefix}_severity"
        )
        selected_symptoms = st.multiselect(
            "Symptoms",
            options=list(SYMPTOM_LABELS),
            default=[tag for tag in draft_data.get("symptoms", []) if tag in SYMPTOM_LABELS],
            key=f"{widget_prefix}_symptoms",
            format_func=lambda tag: SYMPTOM_LABELS[tag],
        )
        selected_impact = st.text_area(
            "Impact",
            value=draft_data.get("impact_summary") or "",
            height=80,
            key=f"{widget_prefix}_impact",
        )
        selected_deployment_ref = st.text_input(
            "Deployment/version",
            value=draft_data.get("deployment_reference") or "",
            key=f"{widget_prefix}_deployment_ref",
        )
        save_clicked = st.form_submit_button("Save incident")

    if save_clicked:
        try:
            reviewed = IncidentDraft(
                transcript=draft_data["transcript"],
                service_id=selected_service or None,
                environment=None if selected_environment == "Not identified" else selected_environment,
                severity=None if selected_severity == "Unspecified" else selected_severity,
                symptoms=selected_symptoms,
                impact_summary=selected_impact.strip() or None,
                deployment_reference=selected_deployment_ref.strip() or None,
                evidence=evidence,
                trace_id=draft_data.get("trace_id"),
            )
            incident_id = workflow.save_reviewed(reviewed, source=source)
            st.session_state[f"saved_incident_{widget_prefix}"] = incident_id
            st.session_state.pop(draft_state_key, None)
            st.rerun()
        except (ValueError, TypeError) as exc:
            st.error(f"Could not save incident: {exc}")


def render_demo_capture() -> None:
    st.subheader("New incident")
    st.caption("Demo uses an editable synthetic transcript. No audio or Gnani calls.")
    if st.button("Run sample incident", key="demo_run_sample"):
        existing = next(
            (
                item
                for item in list_incidents(limit=100)
                if item["source"] == "local-demo" and item["transcript"] == SAMPLE_TRANSCRIPT
            ),
            None,
        )
        if existing:
            incident_id = existing["incident_id"]
        else:
            draft = workflow.extract_candidate(SAMPLE_TRANSCRIPT)
            incident_id = workflow.save_reviewed(draft, source="local-demo")
        st.session_state["saved_incident_demo"] = incident_id
        st.session_state.pop("incident_draft_demo", None)
        st.rerun()

    transcript_text = st.text_area(
        "Incident transcript",
        value=SAMPLE_TRANSCRIPT,
        height=130,
        key="transcript_input",
    )
    if st.button("Extract fields", key="demo_extract"):
        try:
            draft = workflow.extract_candidate(transcript_text, trace_id=new_trace_id())
            st.session_state["incident_draft_demo"] = draft.model_dump(mode="json")
        except ValueError as exc:
            st.error(str(exc))

    if draft_data := st.session_state.get("incident_draft_demo"):
        render_review_form(draft_data, "incident_draft_demo", "demo", "local-demo")
    if incident_id := st.session_state.get("saved_incident_demo"):
        render_incident_result(incident_id)


def render_live_capture() -> None:
    st.subheader("New incident")
    st.caption("Synthetic audio only. WAV clips up to 30 seconds.")
    input_source = st.radio(
        "Source", ["Microphone", "WAV file"], horizontal=True, key="live_audio_source"
    )
    if input_source == "Microphone":
        audio_file = st.audio_input("Record audio", sample_rate=16000, key="live_mic")
    else:
        audio_file = st.file_uploader("Choose WAV file", type=["wav"], key="live_wav_upload")

    if st.button(
        "Transcribe audio",
        disabled=audio_file is None,
        key="live_transcribe",
    ):
        try:
            audio_bytes = audio_file.getvalue()
            duration = validate_wav_duration(audio_bytes, max_seconds=30)
            filename = getattr(audio_file, "name", "incident.wav") or "incident.wav"
            content_type = getattr(audio_file, "type", None) or "audio/wav"
            trace_id = new_trace_id()
            metadata: dict = {"audio_bytes": len(audio_bytes)}
            with trace_scope(trace_id):
                with st.spinner(f"Transcribing {duration:.1f}-second clip..."):
                    with observed_stage(
                        "voice.stt",
                        provider="gnani-prisma-v2.5",
                        metadata=metadata,
                    ):
                        response = transcribe_prisma_v25(
                            audio_bytes,
                            filename=filename,
                            content_type=content_type,
                        )
                        metadata["request_id"] = response.get("request_id")
            st.session_state["live_transcript_editor"] = response.get("transcript", "")
            st.session_state["live_transcription_info"] = {
                "model": response.get("model", "prisma-v2.5"),
                "request_id": response.get("request_id"),
                "trace_id": trace_id,
            }
            st.session_state.pop("incident_draft_live", None)
            st.session_state.pop("saved_incident_live", None)
        except (ValueError, GnaniAPIError, GnaniConfigurationError) as exc:
            st.error(f"Transcription failed: {exc}")

    if "live_transcript_editor" in st.session_state:
        transcription_info = st.session_state.get("live_transcription_info", {})
        st.caption(
            f"{transcription_info.get('model', 'prisma-v2.5')}"
            + (f" - request {transcription_info['request_id']}" if transcription_info.get("request_id") else "")
        )
        reviewed_transcript = st.text_area(
            "Transcript",
            key="live_transcript_editor",
            height=140,
        )
        if st.button("Extract fields", key="live_extract"):
            try:
                draft = workflow.extract_candidate(
                    reviewed_transcript,
                    trace_id=transcription_info.get("trace_id") or new_trace_id(),
                )
                st.session_state["incident_draft_live"] = draft.model_dump(mode="json")
            except ValueError as exc:
                st.error(str(exc))
        if draft_data := st.session_state.get("incident_draft_live"):
            render_review_form(draft_data, "incident_draft_live", "live", "live-stt")

    if incident_id := st.session_state.get("saved_incident_live"):
        render_incident_result(incident_id, allow_tts=True)


st.title("OpsDiary")
live_available = bool(GNANI_API_KEY)
if not live_available and st.session_state.get("app_mode") == "Live":
    st.session_state["app_mode"] = "Demo"
mode_options = ["Demo", "Live"] if live_available else ["Demo"]
mode = st.selectbox("Mode", mode_options, key="app_mode")
if not live_available:
    st.caption("Live mode requires GNANI_API_KEY.")

incidents_now = list_incidents(limit=100)
seed_count = sum(item["source"] == "synthetic-seed" for item in incidents_now)
saved_count = sum(item["source"] in {"local-demo", "live-stt"} for item in incidents_now)
st.caption(f"{seed_count} historical records | {len(services)} services | {saved_count} saved incidents")

new_tab, history_tab = st.tabs(["Incident", "History"])

with new_tab:
    if mode == "Live":
        render_live_capture()
    else:
        render_demo_capture()

with history_tab:
    st.subheader("History")
    all_history = list_incidents(limit=100)
    if not all_history:
        st.caption("No incidents saved yet.")
    else:
        query = st.text_input(
            "Search incidents",
            placeholder="ID, service, symptom, or transcript",
            key="history_search",
        ).strip().casefold()
        history = all_history
        if query:
            history = [
                item
                for item in all_history
                if query
                in " ".join(
                    [
                        item["incident_id"],
                        item.get("transcript", ""),
                        item.get("environment") or "",
                        item.get("severity") or "",
                        item.get("impact_summary") or "",
                        service_by_id.get(item.get("service_id"), {}).get("name", ""),
                        " ".join(SYMPTOM_LABELS.get(tag, tag) for tag in item["symptoms"]),
                    ]
                ).casefold()
            ]
        if not history:
            st.caption("No incidents match this search.")
        else:
            summary_rows = []
            for item in history:
                summary_rows.append(
                    {
                        "Incident": item["incident_id"],
                        "Created (UTC)": item["created_at"],
                        "Service": service_by_id.get(item.get("service_id"), {}).get("name", "Unknown"),
                        "Environment": item.get("environment") or "Unspecified",
                        "Severity": item.get("severity") or "Unspecified",
                        "Symptoms": ", ".join(SYMPTOM_LABELS.get(tag, tag) for tag in item["symptoms"]),
                        "Source": item["source"],
                    }
                )
            st.table(summary_rows)
            incident_ids = [item["incident_id"] for item in history]
            if st.session_state.get("history_incident") not in incident_ids:
                st.session_state.pop("history_incident", None)
            selected_history_id = st.selectbox("Incident", incident_ids, key="history_incident")
            analysis = workflow.analyze(selected_history_id)
            if analysis:
                selected_incident = analysis.incident
                st.write(selected_incident["transcript"])
                st.caption(
                    "Symptoms: "
                    + (", ".join(SYMPTOM_LABELS.get(tag, tag) for tag in selected_incident["symptoms"]) or "none")
                )
                render_enrichment(analysis.service_context)
                st.markdown("**Historical matches**")
                render_pattern_evidence(analysis.pattern_result)
                render_related_records(analysis.related_records)
                if mode == "Live":
                    render_speech_controls(selected_incident, analysis.summary, "history")
                render_report_download(selected_incident, analysis.report, "history")
