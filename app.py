from flask import Flask, render_template, request, redirect, url_for, session
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


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")


@app.route("/summary", methods=["POST"])
def summary():
    email = request.form.get("email")
    user_data = {
        "age": request.form.get("age", ""),
        "sex": request.form.get("sex", ""),
        "symptoms": request.form.get("symptoms", ""),
        "conditions": request.form.get("conditions", ""),
        "allergies": request.form.get("allergies", ""),
        "medications": request.form.get("medications", ""),
        "onset": request.form.get("onset", ""),
        "better": request.form.get("better", ""),
        "worse": request.form.get("worse", ""),
        "severity": request.form.get("severity", ""),
        "treatments": request.form.get("treatments", "")
    }

    prompt = f"""You are a helpful AI doctor. Based on the following patient input, generate a detailed but easy-to-understand educational summary. Include possible explanations, recommended over-the-counter treatments, home remedies, and red flags to watch for. Always include a disclaimer that this is educational only and not a substitute for seeing a doctor.


    Patient Info:

    Age: {user_data['age']}

    Sex: {user_data['sex']}

    Symptoms: {user_data['symptoms']}

    Conditions: {user_data['conditions']}

    Allergies: {user_data['allergies']}

    Medications: {user_data['medications']}

    Onset: {user_data['onset']}

    Better With: {user_data['better']}

    Worse With: {user_data['worse']}

    Severity: {user_data['severity']}

    Treatments Tried: {user_data['treatments']}

    """

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )

    summary_text = response.choices[0].message.content.strip()
    session["summary"] = summary_text
    session["email"] = email
    session["subscribed"] = is_subscribed(email)
    session["used"] = session.get("used", False)

    return render_template("summary.html", summary=summary_text, subscribed=session["subscribed"], used=session["used"])


@app.route("/followup", methods=["POST"])
def followup():
    question = request.form.get("followup")
    summary = session.get("summary", "")
    prompt = f"{summary}

Follow-up question: {question}

Answer:"

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}]
    )
    answer = response.choices[0].message.content.strip()

    email = session.get("email", "")
    subscribed = is_subscribed(email)

    session["used"] = True

    return render_template("summary.html", summary=summary, followup=question, followup_answer=answer, subscribed=subscribed, used=True)
