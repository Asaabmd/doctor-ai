from flask import Flask, render_template, request, jsonify
import openai
import json
import os

app = Flask(__name__)

SUBSCRIPTIONS_FILE = "subscriptions.json"
USAGE_FILE = "usage.json"

openai.api_key = os.getenv("OPENAI_API_KEY")

def build_prompt(inputs):
    return f"""
You are a helpful AI doctor. Summarize the following symptoms and provide a differential diagnosis, red flags, home remedies, and over-the-counter options.

Symptoms: {inputs['symptoms']}
Existing Conditions: {inputs['conditions']}
Allergies: {inputs['allergies']}
Medications: {inputs['medications']}
Onset: {inputs['onset']}
Better with: {inputs['better']}
Worse with: {inputs['worse']}
Severity: {inputs['severity']}
Tried treatments: {inputs['tried']}

Important: This is for educational purposes only and not a substitute for medical advice.
"""

def is_subscribed(email):
    if not os.path.exists(SUBSCRIPTIONS_FILE):
        return False
    with open(SUBSCRIPTIONS_FILE, "r") as f:
        subs = json.load(f)
    return subs.get(email, {}).get("status") == "active"

def has_used(email):
    if not os.path.exists(USAGE_FILE):
        return False
    with open(USAGE_FILE, "r") as f:
        used = json.load(f)
    return email in used

def log_usage(email):
    used = {}
    if os.path.exists(USAGE_FILE):
        with open(USAGE_FILE, "r") as f:
            used = json.load(f)
    used[email] = True
    with open(USAGE_FILE, "w") as f:
        json.dump(used, f)

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    data = request.json
    email = data.get("email")

    if not email:
        return jsonify({"error": "Email is required."}), 400

    if not is_subscribed(email) and has_used(email):
        return jsonify({"error": "free_limit_reached"}), 403

    prompt = build_prompt(data)
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )

    summary = response.choices[0].message.content
    if not is_subscribed(email):
        log_usage(email)

    return jsonify({"summary": summary})

@app.route("/followup", methods=["POST"])
def followup():
    data = request.json
    email = data.get("email")
    question = data.get("question")
    summary = data.get("summary")

    if not is_subscribed(email):
        return jsonify({"error": "Subscription required for follow-up."}), 403

    followup_prompt = f"""
User previously received this summary:
"{summary}"

Now the user asks: {question}

Please respond in a helpful and educational manner.
"""

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": followup_prompt}]
    )

    followup_answer = response.choices[0].message.content
    return jsonify({"followup": followup_answer})

@app.route("/webhook", methods=["POST"])
def webhook():
    event = request.json
    email = event.get("email")
    event_type = event.get("event")

    with open(SUBSCRIPTIONS_FILE, "r") as f:
        subs = json.load(f)

    if event_type in ["subscription.created", "subscription.updated", "subscription.paid"]:
        subs[email] = {"status": "active"}
    elif event_type in ["subscription.deleted", "subscription.refunded"]:
        subs[email] = {"status": "inactive"}

    with open(SUBSCRIPTIONS_FILE, "w") as f:
        json.dump(subs, f)

    return "", 200

if __name__ == "__main__":
    app.run(debug=True)
