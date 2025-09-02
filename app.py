from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import openai
import os
import json
import logging
from datetime import datetime

# ---------- Logging ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)
log = logging.getLogger("doctor-ai")

# ---------- Flask / OpenAI ----------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-this-key")

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
if OPENAI_API_KEY:
    openai.api_key = OPENAI_API_KEY
else:
    log.warning("OPENAI_API_KEY is not set. Summaries will show a friendly error message instead of 500.")

SUBSCRIPTIONS_FILE = "subscriptions.json"

# ---------- Subscription helpers ----------
def load_subs() -> dict:
    try:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            return json.load(f)
    except Exception as e:
        # fine if file doesn't exist yet
        return {}

def save_subs(d: dict) -> None:
    try:
        with open(SUBSCRIPTIONS_FILE, "w") as f:
            json.dump(d, f)
    except Exception as e:
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

# ---------- Webhook to update subscriptions ----------
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
        # ignore unknown events but 200 OK so provider doesn't retry
        return jsonify({"ok": True, "ignored_event": event or "(none)"}), 200

    save_subs(subs)
    # live-refresh current session if the same user
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

        prompt = (
            "You are a helpful AI healthcare assistant. Using the patient intake below, "
            "write a friendly, easy-to-understand, and strictly educational summary. "
            "Include: possible causes, home measures, over-the-counter options when appropriate, "
            "clear red flags, and when to seek urgent care. End with a strong disclaimer that "
            "this is not medical advice.\n\n"
            f"Patient Intake:\n" + "\n".join([f"- {k}: {v}" for k, v in payload.items()])
        )

        summary_text = None
        if not OPENAI_API_KEY:
            summary_text = ("⚠️ OpenAI API key is not configured on the server. "
                            "The app cannot generate a summary right now.")
        else:
            try:
                resp = openai.ChatCompletion.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "You are a helpful healthcare assistant (education only)."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.6,
                )
                summary_text = resp.choices[0].message.content.strip()
            except Exception as e:
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
    except Exception as e:
        log.exception("Unhandled error in /submit")
        # Show a graceful page instead of 500
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

            # Re-check subscription in case webhook/cookie changed
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

            answer = None
            if not OPENAI_API_KEY:
                answer = "⚠️ OpenAI API key is not configured on the server."
            else:
                try:
                    followup_prompt = (
                        "The following is an educational summary previously given to a user. "
                        "Answer the user's follow-up question clearly and compassionately. "
                        "Remind them this is educational only.\n\n"
                        f"Summary:\n{prev_summary}\n\n"
                        f"Follow-up question:\n{question}"
                    )
                    resp = openai.ChatCompletion.create(
                        model="gpt-4",
                        messages=[
                            {"role": "system", "content": "You are a helpful healthcare assistant (education only)."},
                            {"role": "user", "content": followup_prompt},
                        ],
                        temperature=0.6,
                    )
                    answer = resp.choices[0].message.content.strip()
                except Exception as e:
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

        # GET render
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

# Simple health endpoint
@app.route("/health")
def health():
    return jsonify({"ok": True, "time": datetime.utcnow().isoformat()})

@app.route("/reset")
def reset():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)