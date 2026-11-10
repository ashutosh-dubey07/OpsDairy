"""Credit-free deterministic FAQ and evidence-backed local incident search."""

from dataclasses import dataclass
import re
from pathlib import Path

from opsdiary.retrieval import retrieve_incidents
from opsdiary.settings import DATABASE_PATH
from opsdiary.storage import MAX_ASSISTANT_QUERY_CHARS

_NON_WORD = re.compile(r"[^\w\s]", re.UNICODE)

GREETINGS = {
    "hi", "hii", "hiii", "hello", "hey", "namaste", "namaskar",
    "good morning", "good afternoon", "good evening", "kaise ho",
}
THANKS = {"thanks", "thank you", "thx", "shukriya", "dhanyavaad"}


@dataclass(frozen=True)
class AssistantReply:
    answer: str
    intent: str
    source: str
    evidence: list[dict]


def _normalize(text: str) -> str:
    return " ".join(_NON_WORD.sub(" ", text.casefold()).split())


def _faq_reply(normalized: str) -> AssistantReply | None:
    if normalized in GREETINGS:
        return AssistantReply(
            "Hi! OpsDiary ready hai. Incident note ya saved history ke baare mein poochho.",
            "greeting",
            "local-faq",
            [],
        )
    if normalized in THANKS:
        return AssistantReply(
            "You’re welcome. Main local incident context dhoondhne mein madad kar sakta hoon.",
            "thanks",
            "local-faq",
            [],
        )
    if normalized in {
        "help", "what can you do", "what can opsdiary do", "opsdiary kya kar sakta hai",
        "main kya pooch sakta hoon", "how do i use this",
    }:
        return AssistantReply(
            "OpsDiary incident notes ko structure karta hai, saved history mein matching records dhoondhta hai, "
            "aur unke evidence IDs dikhata hai. Search lexical hai; yeh outage predict ya remediate nahi karta.",
            "help",
            "local-faq",
            [],
        )
    if normalized in {
        "what is opsdiary", "what is ops diary", "opsdiary kya hai", "ops diary kya hai",
    }:
        return AssistantReply(
            "OpsDiary Hinglish on-call notes ko structured incidents, service/deployment context, "
            "aur evidence-backed local history mein organize karta hai.",
            "product_info",
            "local-faq",
            [],
        )
    if any(term in normalized.split() for term in {"credit", "credits", "quota"}) or "api call" in normalized:
        return AssistantReply(
            "Ask aur local history search koi AI, Prisma, ya Timbre request nahi bhejte; inka Gnani credit use zero hai. "
            "Credits sirf GNANI_API_KEY configured hone par Transcribe audio, Transcribe update, ya Speak summary button dabane par lag sakte hain.",
            "credit_usage",
            "local-faq",
            [],
        )
    if any(term in normalized.split() for term in {"predict", "prediction", "predicts"}) or "outage forecast" in normalized:
        return AssistantReply(
            "Nahi. OpsDiary historical evidence dikhata hai; outage prediction ya remediation nahi karta.",
            "prediction_scope",
            "local-faq",
            [],
        )
    if any(term in normalized.split() for term in {"data", "database", "stored", "save", "saved"}) and any(
        term in normalized.split() for term in {"where", "kahan", "store", "stored", "save", "saved"}
    ):
        return AssistantReply(
            "Ask questions and answers are saved in the local SQLite database at data/opsdiary.sqlite3 "
            "unless OPSDIARY_DATABASE_PATH is set. The database file is local and is not encrypted by this app.",
            "data_location",
            "local-faq",
            [],
        )
    if normalized in {"how do i record an incident", "incident kaise save karu", "how to save incident"}:
        return AssistantReply(
            "Incident tab mein synthetic Hinglish clip record ya WAV upload karo, Transcribe audio dabao, "
            "transcript review karo, phir fields extract/edit karke incident save karo.",
            "incident_workflow",
            "local-faq",
            [],
        )
    return None


def answer_question(
    query: str,
    db_path: Path | str = DATABASE_PATH,
) -> AssistantReply:
    """Answer common questions locally, otherwise search saved incident evidence."""
    if not isinstance(query, str):
        raise ValueError("Question must be text.")
    clean_query = query.strip()
    if not 1 <= len(clean_query) <= MAX_ASSISTANT_QUERY_CHARS:
        raise ValueError("Question must be between 1 and 2,000 characters.")

    if reply := _faq_reply(_normalize(clean_query)):
        return reply

    matches = retrieve_incidents(clean_query, limit=5, db_path=db_path)
    if not matches:
        return AssistantReply(
            "Koi matching local incident record nahi mila. Service name, environment, ya symptom ke "
            "specific words try karo. Yeh lexical search hai; no match ka matlab incident kabhi nahi hua, yeh nahi hai.",
            "incident_search_no_match",
            "sqlite-fts5",
            [],
        )

    count = len(matches)
    noun = "record" if count == 1 else "records"
    lines = [
        f"SQLite lexical search mein {count} local {noun} match hue. Similar wording shared cause ya prediction prove nahi karti."
    ]
    evidence = []
    for match in matches:
        incident_id = match["incident_id"]
        matched_terms = match["matched_terms"]
        lines.append(
            f"{incident_id} ({match['created_at']} UTC; terms: {', '.join(matched_terms)}): "
            f"{match['evidence_excerpt']}"
        )
        evidence.append(
            {
                "incident_id": incident_id,
                "created_at": match["created_at"],
                "matched_terms": matched_terms,
                "source": match["source"],
            }
        )
    return AssistantReply("\n\n".join(lines), "incident_search", "sqlite-fts5", evidence)
