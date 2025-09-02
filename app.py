from flask import Flask, render_template, request, redirect, session, url_for
import openai
import os
import json

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "defaultsecret")

SUBSCRIPTIONS_FILE = "subscriptions.json"
openai.api_key = os.getenv("OPENAI_API_KEY")

def is_subscribed(email):
    try:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            subs = json.load(f)
        return subs.get(email.lower(), {}).get("status") == "active"
    except:
        return False

def ask_chatgpt(prompt):
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a helpful medical AI for educational purposes only."},
            {"role": "user", "content": prompt}
        ]
    )
    return response['choices'][0]['message']['content']

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/summary", methods=["POST"])
def summary():
    form = request.form
    email = form.get("email", "").strip().lower()
    subscribed = is_subscribed(email)
    session["email"] = email
    session["subscribed"] = subscribed

    user_input = {
        "age": form.get("age", ""),
        "sex": form.get("sex", ""),
        "symptoms": form.get("symptoms", ""),
        "conditions": form.get("conditions", ""),
        "allergies": form.get("allergies", ""),
        "medications": form.get("medications", ""),
        "onset": form.get("onset", ""),
        "better": form.get("better", ""),
        "worse": form.get("worse", ""),
        "severity": form.get("severity", ""),
        "tried": form.get("tried", "")
    }

    prompt = f"""
Patient info:
- Age: {user_input['age']}
- Sex: {user_input['sex']}

Symptoms: {user_input['symptoms']}
Medical Conditions: {user_input['conditions']}
Allergies: {user_input['allergies']}
Medications: {user_input['medications']}
Onset: {user_input['onset']}
What makes it better: {user_input['better']}
What makes it worse: {user_input['worse']}
Severity: {user_input['severity']}
Tried treatments: {user_input['tried']}

Generate a detailed educational summary including possible conditions, red flags, and when to see a doctor.
"""

    summary_response = ask_chatgpt(prompt)
    session["summary"] = summary_response
    return render_template("summary.html", summary=summary_response, subscribed=subscribed)

@app.route("/followup", methods=["POST"])
def followup():
    question = request.form.get("followup", "")
    summary = session.get("summary", "")
    prompt = f"""Previous educational summary:
{summary}

Follow-up question:
{question}"""
    answer = ask_chatgpt(prompt)
    return render_template("summary.html", summary=summary, followup=answer, subscribed=session.get("subscribed", False))
