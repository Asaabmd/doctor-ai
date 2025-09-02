from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os, json, logging
from datetime import datetime

# -------- Logging --------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("doctor-ai")

# -------- Flask --------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-this-key")

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
if not OPENAI_API_KEY:
    log.warning("OPENAI_API_KEY not set. Summaries will show a friendly message.")

# Try to support BOTH OpenAI SDK versions:
# v1: from openai import OpenAI  -> client.chat.completions.create(...)
# legacy: import openai -> openai.ChatCompletion.create(...)
client = None
use_v1_client = False
try:
    # Try v1 client
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()
    use_v1_client = True
    log.info("Using OpenAI v1 client.")
except Exception:
    # Fallback: legacy
    try:
        import openai  # type: ignore
        if OPENAI_API_KEY:
            openai.api_key = OPENAI_API_KEY
        client = openai
        use_v1_client = False
        log.info("Using legacy OpenAI client.")
    except Exception as e:
        client = None
        log.exception("Failed to import any OpenAI client")

SUBSCRIPTIONS_FILE = "subscriptions.json"

# -------- Subscription helpers --------
def load_subs() -> dict:
    try:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_subs(d: dict) -> None:
    try:
        with open(SUBSCRIPTIONS_FILE, "w") as f:
            json.dump(d, f)
    except Exception:
        log.exception("Failed to write subscriptions.json")

def is_subscribed_via_file(email: str) -> bool:
    if not email:
        return False
    subs = load_subs()
    return subs.get(email.lower().strip(), {}).get("status") == "active"

def is_subscribed(email: str, req=None) -> bool:
    file_access = is_subscribed_via_file(email)
    cookie_access = False
    try:
        if req is not None:
            cookie_access = (req.cookies.get("access_granted") == "true")
    except Exception:
        pass
    return bool(file_access or cookie_access)

# -------- OpenAI helpers (dual mode) --------
def chat_complete(messages, temperature=0.6):
    """Call OpenAI chat completions across SDK versions."""
    if not OPENAI_API_KEY or not client:
        raise RuntimeError("OpenAI API key or client not configured")

    if use_v1_client:
        # v1 style
        resp = client.chat.completions.create(
            model="gpt-4o-mini",  # fast/cheap; change to gpt-4o if you prefer
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message.content
    else:
        # legacy style
        resp = client.ChatCompletion.create(
            model="gpt-4",
            messages=messages,
            temperature=temperature,
        )
        return resp.choices[0].message["content"]

def build_summary_prompt(payload: dict) -> str:
    return (
        "You are a helpful AI healthcare assistant. Using the patient intake below, "
        "write a friendly, easy-to-understand, and strictly educational summary. "
        "Include: possible causes, home measures, over-the-counter options when appropriate, "
        "clear red flags, and when to seek urgent care. End with a strong disclaimer that "
        "this is not medical advice.\n\n"
        "Patient Intake:\n" + "\n".join([f"- {k}: {v}" for k, v in payload.items()])
    )

def build_followup_prompt(prev_summary: str, question: str) -> str:
    return (
        "The following is an educational summary previously given to a user. "
        "Answer the user's follow-up question clearly and compassionately. "
        "Remind them this is educational only.\n\n"
        f"Summary:\n{prev_summary}\n\n"
        f"Follow-up question:\n{question}"
    )

# -------- Webhook (keep your Payhip sync) --------
@app.route("/webhook", methods=["POST"])
def webhook():
    payload = request.get_json(silent=True) or {}
    email = (
        payload.get("email")
        or payload.get("customer_email")
        or (payload.get("data") or {}).get("email")
        or ((payload.get("data") or {}).get("customer") or {}).get("email")
        or ""
    )
    email = (email or "").strip().lower()
    event = (payload.get("event") or payload.get("type") or "").strip().lower()

    if not email:
        return jsonify({"ok": False, "error": "missing email"}), 400

    activate = {
        "subscription.created", "subscription.updated", "subscription.paid",
        "subscription.renewed", "subscription.active"
    }
    deactivate = {
        "subscription.cancelled", "subscription.deleted", "subscription.refunded",
        "subscription.expired", "subscription.inactive"
    }

    subs = load_subs()
    if event in activate:
        subs[email] = {"status": "active"}
    elif event in deactivate:
        subs[email] = {"status": "inactive"}
    else:
        return jsonify({"ok": True, "ignored_event": event or "(none)"}), 200

    save_subs(subs)
    try:
        if session.get("email", "").strip().lower() == email:
            session["is_subscribed"] = (subs[email]["status"] == "active")
    except Exception:
        pass

    return jsonify({"ok": True, "email": email, "status": subs[email]["status"]}), 200

# -------- Pages --------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    try:
        email = (request.form.get("email") or "").strip().lower()
        session["email"] = email
        session["is_subscribed"] = is_subscribed(email, request)

        payload = {
            "Sex": request.form.get("sex", ""),
            "Age Group": request.form.get("age_group", ""),
            "Symptoms": request.form.get("symptoms", ""),
            "Existing Conditions": request.form.get("conditions", ""),
            "Allergies": request.form.get("allergies", ""),
            "Medications": request.form.get("medications", ""),
            "Onset": request.form.get("onset", ""),
            "Better With": request.form.get("better", ""),
            "Worse With": request.form.get("worse", ""),
            "Severity": request.form.get("severity", ""),
            "Tried": request.form.get("tried", ""),
        }
        session["intake"] = payload

        if not OPENAI_API_KEY or not client:
            summary_text = ("⚠️ The server is missing the OpenAI API key or SDK. "
                            "Please add OPENAI_API_KEY in your Render Environment and redeploy.")
        else:
            try:
                summary_text = chat_complete(
                    messages=[
                        {"role": "system", "content": "You are a helpful healthcare assistant (education only)."},
                        {"role": "user", "content": build_summary_prompt(payload)},
                    ],
                    temperature=0.6,
                ).strip()
            except Exception:
                log.exception("OpenAI error during summary")
                summary_text = "⚠️ Error generating summary. Please try again in a moment."

        session["summary"] = summary_text or "⚠️ No summary returned."
        session.setdefault("used_followup", False)

        return render_template(
            "summary.html",
            summary=session["summary"],
            is_subscribed=session["is_subscribed"],
            followup_response="",
        )
    except Exception:
        log.exception("Unhandled error in /submit")
        return render_template(
            "summary.html",
            summary="⚠️ Something went wrong while processing your request.",
            is_subscribed=False,
            followup_response=""
        ), 200

@app.route("/summary", methods=["GET", "POST"])
def summary():
    try:
        if request.method == "POST":
            question = (request.form.get("followup") or "").strip()
            prev_summary = session.get("summary", "")

            email = (session.get("email") or "").strip().lower()
            session["is_subscribed"] = is_subscribed(email, request)
            subscribed = session["is_subscribed"]

            if not subscribed and session.get("used_followup", False):
                return render_template(
                    "summary.html",
                    summary=prev_summary,
                    is_subscribed=False,
                    followup_response="This is your one free use. Please subscribe by clicking the link below for continued unlimited access."
                )

            if not OPENAI_API_KEY or not client:
                answer = "⚠️ The server is missing the OpenAI API key or SDK."
            else:
                try:
                    answer = chat_complete(
                        messages=[
                            {"role": "system", "content": "You are a helpful healthcare assistant (education only)."},
                            {"role": "user", "content": build_followup_prompt(prev_summary, question)},
                        ],
                        temperature=0.6,
                    ).strip()
                except Exception:
                    log.exception("OpenAI error during follow-up")
                    answer = "⚠️ Error generating follow-up. Please try again."

            if not subscribed:
                session["used_followup"] = True

            return render_template(
                "summary.html",
                summary=prev_summary,
                is_subscribed=subscribed,
                followup_response=answer
            )

        return render_template(
            "summary.html",
            summary=session.get("summary", ""),
            is_subscribed=session.get("is_subscribed", False),
            followup_response=""
        )
    except Exception:
        log.exception("Unhandled error in /summary")
        return render_template(
            "summary.html",
            summary="⚠️ Something went wrong while loading this page.",
            is_subscribed=False,
            followup_response=""
        ), 200

@app.route("/health")
def health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat()})

@app.route("/reset")
def reset():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)