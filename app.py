from flask import Flask, render_template, request, redirect, url_for, make_response
import openai
import os

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# Prevent caching so users don’t reuse session accidentally
@app.after_request
def add_header(response):
    response.cache_control.no_store = True
    return response

@app.route("/", methods=["GET", "POST"])
def index():
    response_text = None
    followup_mode = False

    use_count = int(request.cookies.get("use_count", 0))

    if use_count >= 1 and request.method == "POST":
        return render_template("index.html", response="🔒 This was a one-time free session. Please subscribe for unlimited access.", use_count=use_count)

    if request.method == "POST":
        # Collect form data
        symptoms = request.form.get("symptoms", "")
        age_range = request.form.get("age_range", "")
        sex = request.form.get("sex", "")
        conditions = request.form.get("existing_conditions", "")
        allergies = request.form.get("allergies", "")
        meds = request.form.get("medications", "")
        onset = request.form.get("onset", "")
        better = request.form.get("better", "")
        worse = request.form.get("worse", "")
        severity = request.form.get("severity", "")
        tried = request.form.get("treatments", "")

        prompt = f"""
You are Doctor AI, a helpful educational triage assistant. Based on the following details, provide a clear, compassionate summary of what might be going on.

Symptoms: {symptoms}
Age: {age_range}
Sex: {sex}
Existing Conditions: {conditions}
Allergies: {allergies}
Medications: {meds}
Onset: {onset}
Improved by: {better}
Worsened by: {worse}
Severity: {severity}
Treatments tried: {tried}

End the summary with a friendly reminder that this is not medical advice and to consult a healthcare professional in person.
"""

        try:
            result = openai.ChatCompletion.create(
                model="gpt-4",
                messages=[
                    {"role": "system", "content": "You are a friendly AI health educator."},
                    {"role": "user", "content": prompt}
                ]
            )
            response_text = result['choices'][0]['message']['content']

            # Add lighthearted professional message
            response_text += "\n\n🩺 Remember: Doctor AI is here to help educate, not replace your real doctor. That would be malpractice! 😉"

        except Exception as e:
            response_text = f"An error occurred: {e}"

        # Set cookie to mark usage
        resp = make_response(render_template("index.html", response=response_text, use_count=1))
        resp.set_cookie("use_count", "1", max_age=60*60*24)
        return resp

    return render_template("index.html", response=None, use_count=use_count)


@app.route("/followup", methods=["POST"])
def followup():
    question = request.form.get("followup", "")
    if not question:
        return redirect(url_for("index"))

    prompt = f"""
You previously provided a health education summary. Now the user has a follow-up question: {question}
Please respond in a clear, educational tone.
"""

    try:
        result = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a friendly AI health educator answering follow-up questions."},
                {"role": "user", "content": prompt}
            ]
        )
        answer = result['choices'][0]['message']['content']
    except Exception as e:
        answer = f"An error occurred: {e}"

    return render_template("index.html", response=answer, use_count=1)

if __name__ == "__main__":
    app.run(debug=True)