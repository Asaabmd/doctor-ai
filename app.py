from flask import Flask, render_template, request, redirect, url_for, session
import openai
import os
import json

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-this-key")
openai.api_key = os.getenv("OPENAI_API_KEY")

SUBSCRIPTIONS_FILE = "subscriptions.json"
USED_EMAILS = set()

def is_subscribed(email):
    try:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            subs = json.load(f)
        return subs.get(email.lower(), {}).get("status") == "active"
    except:
        return False

def ask_chatgpt_summary(data):
    prompt = f"""You are a helpful and informative AI doctor. Provide an educational and detailed summary of the patient's condition based on the following:

Sex: {data['sex']}
Age Group: {data['age']}
Symptoms: {data['symptoms']}
Existing Conditions: {data['conditions']}
Allergies: {data['allergies']}
Current Medications: {data['medications']}
Onset: {data['onset']}
What Makes It Better: {data['better']}
What Makes It Worse: {data['worse']}
Severity: {data['severity']}
What Has Been Tried: {data['tried']}

Clearly explain possible causes, educational insights, and when to seek care. Do NOT provide medical advice or diagnoses."""

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message["content"]

def ask_followup(summary, question):
    prompt = f"""You previously gave this educational summary:\n{summary}\n\nThe patient now asks: {question}\n\nRespond clearly and informatively. This is not medical advice."""
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7
    )
    return response.choices[0].message["content"]

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    email = request.form["email"].strip().lower()
    if not is_subscribed(email) and email in USED_EMAILS:
        return redirect(url_for("limit"))

    data = {k: request.form[k] for k in request.form}
    summary = ask_chatgpt_summary(data)
    session["summary"] = summary
    session["email"] = email
    session["subscribed"] = is_subscribed(email)
    USED_EMAILS.add(email)
    return render_template("summary.html", summary=summary, followup=None, subscribed=session["subscribed"])

@app.route("/followup", methods=["POST"])
def followup():
    question = request.form["followup"]
    summary = session.get("summary", "")
    response = ask_followup(summary, question)
    return render_template("summary.html", summary=summary, followup=response, subscribed=session.get("subscribed", False))

@app.route("/limit")
def limit():
    return "<h3>You have already used your one free session. Please subscribe to continue: <a href='https://payhip.com/b/Da82I'>Subscribe Here</a></h3>"

if __name__ == "__main__":
    app.run(debug=True)