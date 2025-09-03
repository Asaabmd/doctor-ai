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
    log.warning("OPENAI_API_KEY not set. Will use fallback summary; /diag will report missing key.")

# ---------- OpenAI dual-SDK support ----------
client = None
use_v1_client = False
sdk_version = "unknown"
try:
    # New SDK (v1+)
    from openai import OpenAI
    client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else OpenAI()
    use_v1_client = True
    sdk_version = "v1"
    log.info("Using OpenAI v1 client")
except Exception:
    try:
        # Legacy SDK
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
SUBSCRIBED_STATES = {"active", "manual"}  # both count as subscribed

# ---------- Subscription helpers ----------
def _normalize_subs(data) -> dict:
    """
    Normalize JSON into {email: {'status': 'active'|'manual'|'inactive'}}.
    Accepts dict values or plain strings; unknown labels -> 'inactive'.
    """
    norm = {}
    if isinstance(data, dict):
        for k, v in data.items():
            email = (k or "").strip().lower()
            if not email:
                continue
            if isinstance(v, dict):
                status = (v.get("status") or "").strip().lower()
            else:
                status = (str(v) or "").strip().lower()
            if status not in {"active", "manual", "inactive"}:
                status = "inactive"
            norm[email] = {"status": status}
    return norm

def load_subs() -> dict:
    try:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            raw = json.load(f)
            return _normalize_subs(raw)
    except Exception:
        return {}

def save_subs(d: dict) -> None:
    try:
        payload = _normalize_subs(d)
        with open(SUBSCRIPTIONS_FILE, "w") as f:
            json.dump(payload, f)
    except Exception:
        log.exception("Failed to write subscriptions.json")

def is_subscribed_via_file(email: str) -> bool:
    if not email:
        return False
    subs = load_subs()
    rec = subs.get(email.strip().lower())
    if not rec:
        return False
    status = rec.get("status", "").lower()
    return status in SUBSCRIBED_STATES  # 'active' or 'manual'

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
DEFAULT_TEMPERATURE = 0.6
TIMEOUT_SECS = 30

def chat_complete(messages, temperature=DEFAULT_TEMPERATURE):
    """
    Try several models until one succeeds.
    Returns (text, model_used). Raises RuntimeError on failure.
    """
    if not OPENAI_API_KEY or not client:
        raise RuntimeError("OpenAI not configured (missing API key or client)")

    errors = []
    if use_v1_client:
        for m in TRY_MODELS_V1:
            try:
                resp = client.chat.completions.create(
                    model=m, messages=messages, temperature=temperature, timeout=TIMEOUT_SECS
                )
                return resp.choices[0].message.content, m
            except Exception as e:
                errors.append(f"{m}: {e}")
        raise RuntimeError("All v1 models failed -> " + " | ".join(errors))
    else:
        for m in TRY_MODELS_LEGACY:
            try:
                resp = client.ChatCompletion.create(
                    model=m, messages=messages, temperature=temperature, request_timeout=TIMEOUT_SECS
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

# ---------- Fallback summary (no OpenAI) ----------
def rule_based_summary(payload: dict) -> str:
    parts = []
    sx = payload.get("Symptoms", "").strip()
    sev = payload.get("Severity", "").strip()
    onset = payload.get("Onset", "").strip()
    better = payload.get("Better With", "").strip()
    worse = payload.get("Worse With", "").strip()
    tried = payload.get("Tried", "").strip()
    cond = payload.get("Existing Conditions", "").strip()
    meds = payload.get("Medications", "").strip()
    ageg = payload.get("Age Group", "").strip()
    sex = payload.get("Sex", "").strip()

    parts.append(f"Patient: {ageg or 'Age group not specified'}; Sex: {sex or 'not specified'}.")
    if sx: parts.append(f"Key symptoms: {sx}.")
    if onset: parts.append(f"Started: {onset}.")
    if sev: parts.append(f"Severity reported: {sev} (1–10 scale).")
    if cond: parts.append(f"Existing conditions: {cond}.")
    if meds: parts.append(f"Current meds/supplements: {meds}.")
    if better: parts.append(f"Feels better with: {better}.")
    if worse: parts.append(f"Worse with: {worse}.")
    if tried: parts.append(f"Treatments already tried: {tried}.")

    parts.append("\nPossible next steps (educational):")
    parts.append("- Rest, hydration, and balanced nutrition are broadly helpful for many mild conditions.")
    parts.append("- Consider OTC options only if appropriate for you (check labels for age/condition interactions).")
    parts.append("- Track symptoms: timing, severity changes, triggers, and any associated features (fever, rash, shortness of breath, chest pain, confusion).")
    parts.append("- If symptoms rapidly worsen, new neurological signs occur, or red-flag symptoms appear (severe chest pain, trouble breathing, fainting, uncontrolled bleeding), seek urgent care.")

    parts.append("\nDisclaimer: This summary is for educational purposes only and is not medical advice. Always consult a licensed clinician for diagnosis or treatment.")
    return "\n".join(parts)

# ---------- Webhook (Payhip sync) ----------
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
        # ignore unknown events but return 200 so provider doesn't retry
        return jsonify({"ok": True, "ignored_event": event or "(none)"}), 200

    save_subs(subs)
    try:
        if session.get("email", "").strip().lower() == email:
            session["is_subscribed"] = (subs[email]["status"] in SUBSCRIBED_STATES)
    except Exception:
        pass

    return jsonify({"ok": True, "email": email, "status": subs[email]["status"]}), 200

# ---------- Quick status check ----------
@app.route("/sub_status")
def sub_status():
    email = (request.args.get("email") or session.get("email", "")).strip().lower()
    subs = load_subs()
    return jsonify({
        "email": email,
        "file_status": subs.get(email),
        "cookie_access": request.cookies.get("access_granted") == "true",
        "effective_is_subscribed": is_subscribed(email, request)
    })

# ---------- Diagnostics ----------
@app.route("/diag")
def diag():
    result = { "sdk": sdk_version, "key_present": bool(OPENAI_API_KEY) }
    if not OPENAI_API_KEY or client is None:
        result["openai_status"] = "missing"
        return jsonify(result), 200
    try:
        txt, model_used = chat_complete(
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": "Say PONG."},
            ],
            temperature=0.0,
        )
        result.update({"openai_status":"ok", "model_used":model_used, "reply":txt[:200]})
    except Exception as e:
        result.update({"openai_status":"error", "error":str(e)[:500]})
    return jsonify(result), 200

# ---------- Pages ----------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/submit", methods=["GET", "POST"])
def submit():
    if request.method == "GET":
        # If someone tries to visit /submit directly, redirect to home
        return redirect(url_for("index"))

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

        reason, model_used = "", "n/a"
        try:
            text, model_used = chat_complete(
                messages=[
                    {"role": "system", "content": "You are a helpful healthcare assistant (education only)."},
                    {"role": "user", "content": build_summary_prompt(payload)},
                ],
                temperature=DEFAULT_TEMPERATURE,
            )
            summary_text = text.strip()
        except Exception as e:
            log.exception("OpenAI summary error")
            reason = str(e)
            summary_text = rule_based_summary(payload)

        session["summary"] = summary_text or rule_based_summary(payload)
        session.setdefault("used_followup", False)

        diag = f"(SDK={sdk_version} | model={model_used}" + (f" | reason={reason[:160]}" if reason else "") + ")"
        return render_template(
            "summary.html",
            summary=session["summary"] + f"\n\n{diag}",
            is_subscribed=session["is_subscribed"],
            followup_response=""
        )
    except Exception as e:
        log.exception("Unhandled error in /submit")
        return render_template(
            "summary.html",
            summary=f"⚠️ Unhandled error in /submit: {str(e)[:300]}",
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

            reason, model_used = "", "n/a"
            try:
                answer, model_used = chat_complete(
                    messages=[
                        {"role": "system", "content": "You are a helpful healthcare assistant (education only)."},
                        {"role": "user", "content": build_followup_prompt(prev_summary, question)},
                    ],
                    temperature=DEFAULT_TEMPERATURE,
                )
            except Exception as e:
                log.exception("OpenAI follow-up error")
                reason = str(e)
                answer = ("Thanks for your question. Based on the previous summary, continue supportive care "
                          "unless any red flags develop. For persistent/worsening symptoms, contact your clinician.\n\n"
                          "Disclaimer: educational only, not medical advice.")

            if not subscribed:
                session["used_followup"] = True

            diag = f"(SDK={sdk_version} | model={model_used}" + (f" | reason={reason[:160]}" if reason else "") + ")"
            return render_template(
                "summary.html",
                summary=prev_summary,
                is_subscribed=subscribed,
                followup_response=answer + f"\n\n{diag}"
            )

        return render_template(
            "summary.html",
            summary=session.get("summary", ""),
            is_subscribed=session.get("is_subscribed", False),
            followup_response=""
        )
    except Exception as e:
        log.exception("Unhandled error in /summary")
        return render_template(
            "summary.html",
            summary=f"⚠️ Unhandled error in /summary: {str(e)[:300]}",
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