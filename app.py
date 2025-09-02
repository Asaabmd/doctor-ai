from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import openai
import os
import json

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-this-key")
openai.api_key = os.getenv("OPENAI_API_KEY")

SUBSCRIPTIONS_FILE = "subscriptions.json"

# -------------------------
# Subscription helpers
# -------------------------
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
        # In a read-only filesystem, this would fail—Render typically allows writes to ephemeral disk.
        pass

def is_subscribed_via_file(email: str) -> bool:
    if not email:
        return False
    subs = load_subs()
    return subs.get(email.lower().strip(), {}).get("status") == "active"

def is_subscribed(email: str, req: request = None) -> bool:
    """Primary subscription check = subscriptions.json + optional legacy cookie fallback."""
    file_access = is_subscribed_via_file(email)
    cookie_access = False
    try:
        if req is not None:
            cookie_access = (req.cookies.get("access_granted") == "true")
    except Exception:
        pass
    return bool(file_access or cookie_access)

# -------------------------
# Webhook to update subscriptions.json
# -------------------------
@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Accepts JSON payloads from your billing provider (e.g., Payhip).
    Expected keys (we're flexible): event, email OR customer_email OR nested under data.*
    Events that mark ACTIVE:   subscription.created, subscription.updated, subscription.paid, subscription.renewed
    Events that mark INACTIVE: subscription.cancelled, subscription.deleted, subscription.refunded, subscription.expired
    """
    payload = request.get_json(silent=True) or {}

    # Extract email defensively from common shapes
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
        return jsonify({"ok": False, "error": "missing email in payload"}), 400

    # Determine new status by event
    activate_events = {
        "subscription.created", "subscription.updated", "subscription.paid", "subscription.renewed", "subscription.active"
    }
    deactivate_events = {
        "subscription.cancelled", "subscription.deleted", "subscription.refunded", "subscription.expired", "subscription.inactive"
    }

    subs = load_subs()
    if event in activate_events:
        subs[email] = {"status": "active"}
    elif event in deactivate_events:
        subs[email] = {"status": "inactive"}
    else:
        # Unknown event: do nothing, but acknowledge
        return jsonify({"ok": True, "ignored_event": event or "(none)"}), 200

    save_subs(subs)

    # If the current session user is this email, refresh session flag immediately
    try:
        if session.get("email", "").strip().lower() == email:
            session["is_subscribed"] = (subs[email]["status"] == "active")
    except Exception:
        pass

    return jsonify({"ok": True, "email": email, "status": subs[email]["status"]}), 200

# -------------------------
# Pages
# -------------------------
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    # Collect inputs
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
    except Exception:
        summary_text = "⚠️ Error generating summary. Please try again later."

    session["summary"] = summary_text
    # Free users can have one follow-up; track if it’s been used.
    session.setdefault("used_followup", False)

    return render_template(
        "summary.html",
        summary=summary_text,
        is_subscribed=session["is_subscribed"],
        followup_response="",
    )

@app.route("/summary", methods=["GET", "POST"])
def summary():
    # Handle follow-ups (POST)
    if request.method == "POST":
        question = (request.form.get("followup") or "").strip()
        prev_summary = session.get("summary", "")

        # Re-evaluate subscription (cookie + file) in case it changed via webhook
        email = (session.get("email") or "").strip().lower()
        session["is_subscribed"] = is_subscribed(email, request)
        subscribed = session["is_subscribed"]

        if not subscribed and session.get("used_followup", False):
            # Non-subscribers get only one follow-up
            return render_template(
                "summary.html",
                summary=prev_summary,
                is_subscribed=False,
                followup_response="This is your one free use. Please subscribe by clicking the link below for continued unlimited access."
            )

        followup_prompt = (
            "The following is an educational summary previously given to a user. "
            "Answer the user's follow-up question clearly and compassionately. "
            "Remind them this is educational only.\n\n"
            f"Summary:\n{prev_summary}\n\n"
            f"Follow-up question:\n{question}"
        )

        try:
            resp = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a helpful healthcare assistant (education only)."},
                    {"role": "user", "content": followup_prompt},
                ],
                temperature=0.6,
            )
            answer = resp.choices[0].message.content.strip()
        except Exception:
            answer = "⚠️ Error generating follow-up. Please try again."

        # Mark free user's single follow-up as used
        if not subscribed:
            session["used_followup"] = True

        return render_template(
            "summary.html",
            summary=prev_summary,
            is_subscribed=subscribed,
            followup_response=answer
        )

    # GET -> show the current summary page
    return render_template(
        "summary.html",
        summary=session.get("summary", ""),
        is_subscribed=session.get("is_subscribed", False),
        followup_response=""
    )

@app.route("/reset")
def reset():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)