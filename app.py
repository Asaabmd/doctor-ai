from flask import Flask, render_template, request, redirect, url_for, session
import openai
import os
import json

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-this-key")
openai.api_key = os.getenv("OPENAI_API_KEY")

SUBSCRIPTIONS_FILE = "subscriptions.json"

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
    email = request.form.get("email", "").strip().lower()
    session["email"] = email
    session["used"] = session.get("used", False)
    subscribed = is_subscribed(email)

    if not subscribed and session["used"]:
        return redirect(url_for("subscribe"))

    data = {
        "Age": request.form.get("age", ""),
        "Sex": request.form.get("sex", ""),
        "Symptoms": request.form.get("symptoms", ""),
        "Conditions": request.form.get("conditions", ""),
        "Allergies": request.form.get("allergies", ""),
        "Medications": request.form.get("medications", ""),
        "Onset": request.form.get("onset", ""),
        "Better": request.form.get("better", ""),
        "Worse": request.form.get("worse", ""),
        "Severity": request.form.get("severity", ""),
        "Tried": request.form.get("treatments", "")
    }

    prompt = "You are a helpful AI healthcare assistant. Based on the details provided, create a friendly, informative, and easy-to-understand summary including:
- Possible causes
- Over-the-counter remedies
- Home treatments
- Red flags to watch for

Details:
"
    for k, v in data.items():
        prompt += f"{k}: {v}
"

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        summary_text = response.choices[0].message["content"].strip()
    except Exception as e:
        summary_text = f"Error generating summary: {e}"

    session["used"] = True
    session["subscribed"] = subscribed
    session["summary"] = summary_text

    return render_template("summary.html", summary=summary_text, subscribed=subscribed)

@app.route("/followup", methods=["POST"])
def followup():
    email = session.get("email")
    subscribed = is_subscribed(email)

    if not subscribed and session.get("followed_up"):
        return redirect(url_for("subscribe"))

    question = request.form.get("followup", "")
    context = session.get("summary", "")

    prompt = f"You provided this earlier summary:

{context}

Now the user asks: {question}

Please provide a helpful follow-up answer."

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7
        )
        followup_answer = response.choices[0].message["content"].strip()
    except Exception as e:
        followup_answer = f"Error generating follow-up: {e}"

    session["followed_up"] = True

    return render_template("summary.html", summary=session.get("summary", ""), followup=followup_answer, subscribed=subscribed)

@app.route("/subscribe")
def subscribe():
    return redirect("https://payhip.com/b/Da82I")

if __name__ == "__main__":
    app.run(debug=True)
