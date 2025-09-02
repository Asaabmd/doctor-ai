from flask import Flask, render_template, request, session, redirect
import openai
import os
import json

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "your-secret-key")
openai.api_key = os.getenv("OPENAI_API_KEY")

SUBSCRIPTIONS_FILE = "subscriptions.json"

def is_subscribed(email):
    try:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            data = json.load(f)
        return data.get(email.lower(), {}).get("status") == "active"
    except:
        return False

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/summary", methods=["POST"])
def summary():
    email = request.form.get("email", "").lower()
    if not is_subscribed(email) and session.get("used"):
        return "Access denied. Please subscribe for unlimited access."

    fields = {
        "Symptoms": request.form.get("symptoms", ""),
        "Conditions": request.form.get("conditions", ""),
        "Allergies": request.form.get("allergies", ""),
        "Medications": request.form.get("medications", ""),
        "Start": request.form.get("start", ""),
        "Better": request.form.get("better", ""),
        "Worse": request.form.get("worse", ""),
        "Severity": request.form.get("severity", ""),
        "Tried": request.form.get("tried", ""),
        "Sex": request.form.get("sex", ""),
        "Age": request.form.get("age_group", "")
    }

    session["email"] = email
    session["fields"] = fields
    session["used"] = True

    prompt = f"You are a helpful AI doctor. Based on the following info, provide a clear, educational summary:\n" + json.dumps(fields, indent=2)
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    summary_text = response.choices[0].message.content.strip()
    return render_template("summary.html", summary=summary_text)

@app.route("/followup", methods=["POST"])
def followup():
    email = session.get("email")
    if not is_subscribed(email):
        return "Follow-up only available for subscribed users."

    question = request.form.get("followup", "")
    fields = session.get("fields", {})
    previous_summary = request.form.get("summary", "")

    followup_prompt = f"Patient follow-up question: {question}\n\nOriginal Info:\n{json.dumps(fields, indent=2)}\n\nInitial Summary:\n{previous_summary}"
    followup_response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": followup_prompt}],
        temperature=0.7
    )
    answer = followup_response.choices[0].message.content.strip()
    return render_template("summary.html", summary=previous_summary, followup=answer)
