from flask import Flask, render_template, request, redirect, url_for, session
import openai
import os
import json

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "replace-this-key")
openai.api_key = os.getenv("OPENAI_API_KEY")

SUBSCRIPTIONS_FILE = "subscriptions.json"

def is_subscribed(email: str) -> bool:
    try:
        with open(SUBSCRIPTIONS_FILE, "r") as f:
            subs = json.load(f)
        return subs.get(email.lower(), {}).get("status") == "active"
    except Exception:
        return False

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/submit", methods=["POST"])
def submit():
    # Collect inputs
    email = (request.form.get("email") or "").strip().lower()
    session["email"] = email
    session["is_subscribed"] = is_subscribed(email)

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

    # Build a safe multiline prompt (no unterminated quotes)
    prompt = (
        "You are a helpful AI healthcare assistant. Using the patient intake below, "
        "write a friendly, easy-to-understand, and strictly educational summary. "
        "Include: possible causes, home measures, over-the-counter options when appropriate, "
        "clear red flags, and when to seek urgent care. End with a strong disclaimer that "
        "this is not medical advice.\n\n"
        f"Patient Intake:\n"
        + "\n".join([f"- {k}: {v}" for k, v in payload.items()])
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
    except Exception as e:
        summary_text = "⚠️ Error generating summary. Please try again later."

    session["summary"] = summary_text
    # For free users we allow one summary + one follow-up; we track if they used follow-up later.
    session.setdefault("used_followup", False)

    return render_template("summary.html",
                           summary=summary_text,
                           is_subscribed=session["is_subscribed"],
                           followup_response="")

@app.route("/summary", methods=["GET", "POST"])
def summary():
    # POST here handles a follow-up question
    if request.method == "POST":
        question = (request.form.get("followup") or "").strip()
        prev_summary = session.get("summary", "")

        if not session.get("is_subscribed", False) and session.get("used_followup", False):
            # Non-subscribers get only one follow-up
            return render_template("summary.html",
                                   summary=prev_summary,
                                   is_subscribed=False,
                                   followup_response="This is your one free use. Please subscribe by clicking the link below for continued unlimited access.")

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
        if not session.get("is_subscribed", False):
            session["used_followup"] = True

        return render_template("summary.html",
                               summary=prev_summary,
                               is_subscribed=session.get("is_subscribed", False),
                               followup_response=answer)

    # GET -> show the current summary page
    return render_template("summary.html",
                           summary=session.get("summary", ""),
                           is_subscribed=session.get("is_subscribed", False),
                           followup_response="")

@app.route("/reset")
def reset():
    session.clear()
    return redirect(url_for("index"))

if __name__ == "__main__":
    app.run(debug=True)