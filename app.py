from flask import Flask, render_template, request, redirect, url_for, session, make_response
import openai
import os
import json

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-this-key")

SUBSCRIPTIONS_FILE = "subscriptions.json"
openai.api_key = os.getenv("OPENAI_API_KEY")


def is_subscribed(email):
    try:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            subs = json.load(f)
        return subs.get(email.lower(), {}).get("status") == "active"
    except:
        return False


def ask_chatgpt_summary(symptoms, context):
    prompt = f"""You are a helpful AI doctor. Summarize the following symptoms and provide a differential diagnosis, red flags, home remedies, and over-the-counter options.

Symptoms: {symptoms}
Existing Conditions: {context['existing_conditions']}
Allergies: {context['allergies']}
Medications: {context['medications']}
Onset: {context['onset']}
Better with: {context['better']}
Worse with: {context['worse']}
Severity: {context['severity']}
Tried treatments: {context['treatments']}

Important: This is for educational purposes only and not a substitute for medical advice.
"""
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.choices[0].message.content


def ask_chatgpt_followup(question, summary):
    followup_prompt = f"""
User previously received this summary:
\"{summary}\"

Now the user asks: {question}

Please respond in a helpful and educational manner.
"""
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": followup_prompt}]
    )
    return response.choices[0].message.content


@app.route("/", methods=["GET", "POST"])
def index():
    email = (request.cookies.get("email") or "").strip().lower()
    has_access = request.cookies.get("access_granted") == "true"
    use_count = int(request.cookies.get("use_count", 0))

    if request.method == "POST":
        if not (has_access or is_subscribed(email)) and use_count >= 1:
            return render_template(
                "index.html",
                response="🔒 This free version allows only one summary and one follow-up. Please subscribe for unlimited access.",
                followup_response="",
                use_count=use_count
            )

        email = (request.form.get("email") or "").strip().lower()
        symptoms = request.form.get("symptoms", "").strip()
        context = {
            "existing_conditions": request.form.get("existing_conditions", "skip"),
            "allergies": request.form.get("allergies", "skip"),
            "medications": request.form.get("medications", "skip"),
            "onset": request.form.get("onset", "unknown"),
            "better": request.form.get("better", "unknown"),
            "worse": request.form.get("worse", "unknown"),
            "severity": request.form.get("severity", "unknown"),
            "treatments": request.form.get("treatments", "unknown"),
        }

        try:
            summary = ask_chatgpt_summary(symptoms, context)
        except Exception as e:
            summary = f"⚠️ Error generating summary: {e}"

        session["summary"] = summary
        session["email"] = email
        session["use_count"] = use_count + 1

        resp = redirect(url_for("summary_page"))
        resp.set_cookie("email", email, max_age=60 * 60 * 24 * 365)
        if not (has_access or is_subscribed(email)):
            resp.set_cookie("use_count", str(use_count + 1), max_age=60 * 60 * 24 * 30)
        return resp

    return render_template("index.html", response="", followup_response="", use_count=use_count)


@app.route("/summary", methods=["GET", "POST"])
def summary_page():
    summary = session.get("summary", "")
    email = session.get("email", "").strip().lower()
    use_count = session.get("use_count", 0)
    has_access = request.cookies.get("access_granted") == "true"
    followup_answer = ""

    if request.method == "POST":
        if not (has_access or is_subscribed(email)) and use_count >= 2:
            followup_answer = "🔒 You’ve reached the free follow-up limit. Please subscribe to ask more questions."
        else:
            question = request.form.get("followup", "").strip()
            try:
                followup_answer = ask_chatgpt_followup(question, summary)
                session["use_count"] = use_count + 1
            except Exception as e:
                followup_answer = f"⚠️ Error generating follow-up: {e}"

    return render_template("summary.html", response=summary, followup_response=followup_answer)


@app.route("/webhook", methods=["POST"])
def webhook():
    event = request.json
    email = event.get("email", "").strip().lower()
    event_type = event.get("event")

    try:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            subs = json.load(f)
    except:
        subs = {}

    if event_type in ["subscription.created", "subscription.updated", "subscription.paid"]:
        subs[email] = {"status": "active"}
    elif event_type in ["subscription.deleted", "subscription.refunded"]:
        subs[email] = {"status": "inactive"}

    with open(SUBSCRIPTIONS_FILE, "w") as f:
        json.dump(subs, f)

    return "", 200


if __name__ == "__main__":
    app.run(debug=True)