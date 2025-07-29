from flask import Flask, render_template, request
import openai
import os

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY") or "sk-your-openai-key"


def ask_chatgpt(symptoms: str, context: dict) -> str:
    context_summary = "\n".join([
        f"Age Range: {context.get('age_range', 'unknown')}",
        f"Sex/Gender: {context.get('sex', 'unknown')}",
        f"Known Conditions: {context.get('existing_conditions', 'unknown')}",
        f"Allergies: {context.get('allergies', 'unknown')}",
        f"Medications: {context.get('medications', 'unknown')}",
        f"Onset: {context.get('onset', 'unknown')}",
        f"What Makes It Better: {context.get('better', 'unknown')}",
        f"What Makes It Worse: {context.get('worse', 'unknown')}",
        f"Severity (1-10): {context.get('severity', 'unknown')}",
        f"Treatments Tried: {context.get('treatments', 'unknown')}"
    ])
    prompt = (
        f"You are a board-certified family medicine physician writing an educational summary.\n\n"
        f"Patient profile and HPI:\n{context_summary}\n\n"
        f"Reported symptoms:\n{symptoms}\n\n"
        f"Please include:\n"
        f"1. Differential diagnosis (possible causes)\n"
        f"2. Common OTC medications (avoid Rx)\n"
        f"3. Home/lifestyle measures\n"
        f"4. Red flags requiring urgent care\n"
        f"5. Strong disclaimer that this is educational only\n\n"
        f"Use clear headings and bullet points. Consider timing, severity, and prior treatments to guide the response."
    )
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{
            "role":
            "system",
            "content":
            ("You are a cautious, educational AI medical assistant. Avoid treatment or diagnostic claims."
             )
        }, {
            "role": "user",
            "content": prompt
        }],
        temperature=0.6)
    return response['choices'][0]['message']['content']


@app.route("/", methods=["GET", "POST"])
def index():
    output = ""
    if request.method == "POST":
        symptoms = request.form.get("symptoms", "")
        context = {
            "age_range": request.form.get("age_range", "skip"),
            "sex": request.form.get("sex", "skip"),
            "existing_conditions": request.form.get("existing_conditions",
                                                    "skip"),
            "allergies": request.form.get("allergies", "skip"),
            "medications": request.form.get("medications", "skip"),
            "onset": request.form.get("onset", "unknown"),
            "better": request.form.get("better", "unknown"),
            "worse": request.form.get("worse", "unknown"),
            "severity": request.form.get("severity", "unknown"),
            "treatments": request.form.get("treatments", "unknown"),
        }
        try:
            output = ask_chatgpt(symptoms, context)
        except Exception as e:
            output = f"⚠️ Error: {e}"
    return render_template("index.html", response=output)


from flask import render_template, request


@app.route("/", methods=["GET", "POST"])
def index():
    output = ""
    if request.method == "POST":
        symptoms = request.form.get("symptoms", "")
        output = f"You said: {symptoms}"  # or call your ChatGPT function here
    return render_template("index.html", response=output)


if __name__ == "__main__":
    app.run(host='0.0.0.0', port=3000, debug=True)
