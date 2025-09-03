from flask import Flask, render_template, request, redirect, url_for, session, make_response, jsonify
import os
import json
import openai

# ----------------- App Setup -----------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-this-key")

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SUBSCRIPTIONS_FILE = os.path.join(BASE_DIR, "subscriptions.json")

# OpenAI
openai.api_key = os.getenv("OPENAI_API_KEY")

# ----------------- Subscription Helpers -----------------
def load_subscriptions():
    try:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_subscriptions(data):
    try:
        with open(SUBSCRIPTIONS_FILE, "w") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def is_subscribed(email: str) -> bool:
    """
    Treat a user as subscribed if:
      - subs[email]['status'] == 'active', OR
      - subs[email].get('manual') == True  (courtesy/manual)
    """
    if not email:
        return False
    subs = load_subscriptions()
    rec = subs.get(email.lower().strip())
    if not rec:
        return False
    status = rec.get("status", "").lower()
    manual = bool(rec.get("manual"))
    return status == "active" or manual

# ----------------- OpenAI Calls -----------------
def compose_summary_prompt(symptoms, context):
    # Build the prompt including Sex and Age Group
    return f"""You are a helpful AI health educator ('My AI Doctor'). Provide an educational summary (NOT medical advice) for the following intake.

Sex: {context.get('sex','unknown')}
Age Group: {context.get('age_group','unknown')}
Symptoms: {symptoms}
Existing Conditions: {context.get('existing_conditions','skip')}
Allergies: {context.get('allergies','skip')}
Medications: {context.get('medications','skip')}
Onset: {context.get('onset','unknown')}
Better with: {context.get('better','unknown')}
Worse with: {context.get('worse','unknown')}
Severity: {context.get('severity','unknown')}
Tried treatments: {context.get('treatments','unknown')}

Please include:
1) A brief plain-English summary of what the symptoms could suggest (differential-style, educational only).
2) Red flags that should prompt urgent in-person assessment.
3) Practical, general home-care measures and over-the-counter options (if appropriate).
4) When to seek routine follow-up vs urgent care.
Important: Clearly state that this is educational information only and not a diagnosis or treatment plan.
"""

def ask_openai_summary(symptoms, context):
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful medical educator. You do not provide diagnosis or treatment; you provide general, educational information only."},
                {"role": "user", "content": compose_summary_prompt(symptoms, context)}
            ],
            temperature=0.3
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"⚠️ Error generating summary: {e}"

def ask_openai_followup(question, summary):
    try:
        followup_prompt = f"""The user previously received this educational summary:
\"\"\"{summary}\"\"\"

Now answer the user's new question below in an educational, non-diagnostic manner. Include helpful next-step considerations and red flags if relevant.

Question: {question}
"""
        resp = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a helpful medical educator. You do not provide diagnosis or treatment; you provide general, educational information only."},
                {"role": "user", "content": followup_prompt}
            ],
            temperature=0.3
        )
        return resp.choices[0].message.content
    except Exception as e:
        return f"⚠️ Error generating follow-up: {e}"

# ----------------- Routes -----------------
@app.route("/", methods=["GET"])
def index():
    # Read cookie to show any prior limit messages if you want later
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    email = (request.form.get("email") or "").strip().lower()
    symptoms = (request.form.get("symptoms") or "").strip()
    sex = (request.form.get("sex") or "").strip()
    age_group = (request.form.get("age_group") or "").strip()

    # Free-tier use count via cookie
    use_count = int(request.cookies.get("use_count", 0))

    if not symptoms:
        # Render index again with a client-side message; but we keep index simple here
        return render_template("index.html")

    subscribed = is_subscribed(email)

    # Enforce free-tier limits: one summary + one follow-up (2 "uses")
    if not subscribed and use_count >= 1:
        # They already consumed the free summary. Redirect with banner at summary step.
        session["summary"] = "🔒 This free version allows only one summary and one follow-up. Please subscribe for unlimited access."
        session["email"] = email
        session["is_subscribed"] = False
        resp = redirect(url_for("summary_page"))
        # keep use_count cookie same for now
        resp.set_cookie("email", email, max_age=60*60*24*365)
        return resp

    # Build context for prompt
    context = {
        "sex": sex or "unknown",
        "age_group": age_group or "unknown",
        "existing_conditions": request.form.get("conditions", "skip"),
        "allergies": request.form.get("allergies", "skip"),
        "medications": request.form.get("medications", "skip"),
        "onset": request.form.get("onset", "unknown"),
        "better": request.form.get("better", "unknown"),
        "worse": request.form.get("worse", "unknown"),
        "severity": request.form.get("severity", "unknown"),
        "treatments": request.form.get("tried", "unknown"),
    }

    summary = ask_openai_summary(symptoms, context)

    # Persist data for summary page
    session["summary"] = summary
    session["email"] = email
    session["is_subscribed"] = subscribed

    # Increment use count only if not subscribed
    resp = redirect(url_for("summary_page"))
    resp.set_cookie("email", email, max_age=60*60*24*365)
    if not subscribed:
        resp.set_cookie("use_count", str(use_count + 1), max_age=60*60*24*30)
    return resp

@app.route("/summary", methods=["GET", "POST"])
def summary_page():
    summary = session.get("summary", "")
    email = (session.get("email") or "").strip().lower()
    is_sub = bool(session.get("is_subscribed", False))
    if not summary:
        return redirect(url_for("index"))

    use_count = int(request.cookies.get("use_count", 0))

    followup_response = ""
    if request.method == "POST":
        if not is_sub and use_count >= 2:
            followup_response = "🔒 This is your one free follow-up. Please subscribe for unlimited questions."
        else:
            question = (request.form.get("followup") or "").strip()
            if question:
                followup_response = ask_openai_followup(question, summary)
                # bump use count for free users
                if not is_sub:
                    new_count = use_count + 1
                    session.modified = True
                    resp = make_response(render_template("summary.html",
                                                         summary=summary,
                                                         followup_response=followup_response,
                                                         is_subscribed=is_sub))
                    resp.set_cookie("use_count", str(new_count), max_age=60*60*24*30)
                    return resp
            else:
                followup_response = "⚠️ Please enter a follow-up question."

    return render_template("summary.html",
                           summary=summary,
                           followup_response=followup_response,
                           is_subscribed=is_sub)

# ----------------- Subscription Webhook & Status -----------------
@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Example payload:
      { "email": "user@example.com", "event": "subscription.created" }
    Events considered active: subscription.created, subscription.updated, subscription.paid
    Events considered inactive: subscription.deleted, subscription.refunded
    """
    event = request.json or {}
    email = (event.get("email") or "").strip().lower()
    event_type = (event.get("event") or "").strip()

    if not email:
        return "", 400

    subs = load_subscriptions()
    if event_type in ["subscription.created", "subscription.updated", "subscription.paid"]:
        rec = subs.get(email, {})
        rec["status"] = "active"
        subs[email] = rec
    elif event_type in ["subscription.deleted", "subscription.refunded"]:
        rec = subs.get(email, {})
        rec["status"] = "inactive"
        subs[email] = rec

    save_subscriptions(subs)
    return "", 200

@app.route("/sub_status", methods=["GET"])
def sub_status():
    email = (request.args.get("email") or "").strip().lower()
    if not email:
        return jsonify({"ok": False, "error": "email query param required"}), 400
    subs = load_subscriptions()
    rec = subs.get(email, {})
    active = is_subscribed(email)
    return jsonify({
        "ok": True,
        "email": email,
        "record": rec,
        "is_subscribed": active
    }), 200

# ----------------- Main -----------------
if __name__ == "__main__":
    # For local dev only. In production (Render), Gunicorn/WSGI runs the app.
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)