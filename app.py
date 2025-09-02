from flask import Flask, render_template, request, redirect, url_for
import openai
import os
import json

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

def is_subscribed(email):
    try:
        with open("subscriptions.json", "r") as f:
            subs = json.load(f)
        return subs.get(email.lower(), {}).get("status") == "active"
    except:
        return False

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/summary", methods=["POST"])
def summary():
    email = request.form["email"].strip().lower()
    sex = request.form.get("sex", "")
    age_group = request.form.get("age_group", "")
    symptoms = request.form.get("symptoms", "")
    context = {
        "conditions": request.form.get("conditions", ""),
        "allergies": request.form.get("allergies", ""),
        "medications": request.form.get("medications", ""),
        "onset": request.form.get("onset", ""),
        "better": request.form.get("better", ""),
        "worse": request.form.get("worse", ""),
        "severity": request.form.get("severity", ""),
        "tried": request.form.get("tried", "")
    }

    full_prompt = f"""You are a helpful AI doctor. Summarize the patient's condition clearly:
Sex: {sex}
Age Group: {age_group}
Symptoms: {symptoms}
Conditions: {context['conditions']}
Allergies: {context['allergies']}
Medications: {context['medications']}
Onset: {context['onset']}
Better: {context['better']}
Worse: {context['worse']}
Severity: {context['severity']}
Tried: {context['tried']}
Respond with an educational, respectful summary in clear language.
"""

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": full_prompt}],
            max_tokens=700
        )
        summary_text = response.choices[0].message.content.strip()
    except Exception as e:
        summary_text = f"Error generating summary: {str(e)}"

    return render_template("summary.html", summary=summary_text, email=email, subscribed=is_subscribed(email))