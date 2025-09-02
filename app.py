from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import os, json, logging
from datetime import datetime

# ---------- Logging ----------
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("doctor-ai")

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-this-key")

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()
if not OPENAI_API_KEY:
    log.warning("OPENAI_API_KEY not set. Will show a friendly error to users.")

# --- Support both OpenAI SDKs ---
client = None
use_v1_client = False
sdk_version = "unknown"
try:
    # v1 client
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()
    use_v1_client = True
    sdk_version = "v1"
    log.info("Using OpenAI v1 client")
except Exception:
    try:
        # legacy client
        import openai  # type: ignore
        if OPENAI_API_KEY:
            openai.api_key = OPENAI_API_KEY
        client = openai
        use_v1_client = False
        sdk_version = "legacy"
        log.info("Using legacy OpenAI client")
    except Exception:
        client = None
        sdk_version = "none"
        log.exception("No OpenAI client available")

SUBSCRIPTIONS_FILE = "subscriptions.json"

# ---------- Subscription helpers ----------
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

# ---------- OpenAI helpers ----------
TRY_MODELS_V1 = ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"]
TRY_MODELS_LEGACY = ["gpt-4", "gpt-3.5-turbo"]

def chat_complete(messages, temperature=0.6):
    """
    Try several models until one succeeds.
    Returns (text, model_used) or raises RuntimeError with detail.
    """
    if not OPENAI_API_KEY or not client:
        raise RuntimeError("OpenAI client or API key not configured")

    errors = []
    if use_v1_client:
        for m in TRY_MODELS_V1:
            try:
                resp = client.chat.completions.create(
                    model=m,
                    messages=messages,
                    temperature=temperature,
                )
                return resp.choices[0].message.content, m
            except Exception as e:
                errors.append(f"{m}: {e}")
        raise RuntimeError("All v1 models failed -> " + " | ".join(errors))
    else:
        for m in TRY_MODELS_LEGACY:
            try:
                resp = client.ChatCompletion.create(
                    model=m,
                    messages=messages,
                    temperature=temperature,
                )
                return resp.choices[0].message["content"], m
            except Exception as e:
                errors.append(f"{m}: {e}")
        raise RuntimeError("All legacy models failed -> " + " | ".join(errors))

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

# ---------- Webhook ----------
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

    activate = {"subscription.created","subscription.updated","subscription.paid","subscription.renewed","subscription.active"}
    deactivate = {"subscription.cancelled","subscription.deleted","subscription.refunded","subscription.expired","subscription.inactive"}

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

# ---------- Pages ----------
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

        if not OPENAI_API_KEY or client is None:
            summary_text = ("⚠️ OpenAI is not configured on the server. "
                            "Ask your admin to set OPENAI_API_KEY and redeploy.")
            reason = "Missing API key or SDK"
            model_used = "n/a"
        else:
            try:
                summary_text, model_used = chat_complete(
                    messages=[
                        {"role": "system", "content": "You are a helpful healthcare assistant (education only)."},
                        {"role": "user", "content": build_summary_prompt(payload)},
                    ],
                    temperature=0.6,
                )
                reason = ""
            except Exception as e:
                log.exception("OpenAI summary error")
                summary_text = "⚠️ Error generating summary. Please try again shortly."
                reason = str(e)
                model_used = "n/a"

        # Save & render
        session["summary"] = summary_text or "⚠️ No summary returned."
        session.setdefault("used_followup", False)

        # Show a tiny diagnostics line (safe, masked) to help you fix quickly
        diag = f"(SDK={sdk_version} | model={model_used} | reason={reason[:160]})" if reason else f"(SDK={sdk_version} | model={model_used})"

        return render_template(
            "summary.html",
            summary=session["summary"] + ("\n\n" + diag if diag else ""),
            is_subscribed=session["is_subscribed"],
            followup_response="",
        )
    except Exception as e:
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

            if not OPENAI_API_KEY or client is None:
                answer = "⚠️ OpenAI is not configured on the server."
                reason = "Missing API key or SDK"
                model_used = "n/a"
            else:
                try:
                    answer, model_used = chat_complete(
                        messages=[
                            {"role": "system", "content": "You are a helpful healthcare assistant (education only)."},
                            {"role": "user", "content": build_followup_prompt(prev_summary, question)},
                        ],
                        temperature=0.6,
                    )
                    reason = ""
                except Exception as e:
                    log.exception("OpenAI follow-up error")
                    answer = "⚠️ Error generating follow-up. Please try again."
                    reason = str(e)
                    model_used = "n/a"

            if not subscribed:
                session["used_followup"] = True

            diag = f"(SDK={sdk_version} | model={model_used} | reason={reason[:160]})" if reason else f"(SDK={sdk_version} | model={model_used})"

            return render_template(
                "summary.html",
                summary=prev_summary,
                is_subscribed=subscribed,
                followup_response=answer + ("\n\n" + diag if diag else "")
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
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat(), "sdk": sdk_version})

@app.route("/reset")
def reset():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)