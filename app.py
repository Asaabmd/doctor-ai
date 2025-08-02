from flask import Flask, render_template, request
import openai
import os

app = Flask(__name__)

# Set your OpenAI API key securely
openai.api_key = os.getenv("OPENAI_API_KEY")

# Function to create the summary based on symptom + context
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
        f"Severity (1–10): {context.get('severity', 'unknown')}",
        f"Treatments Tried: {context.get('treatments', 'unknown')}"
    ])

    prompt = (
        f"You are a board-certified family physician writing an educational summary.\n\n"
        f"Patient profile and HPI:\n{context_summary}\n\n"
        f"Reported symptoms:\n{symptoms}\n\n"
        f"Please include:\n"
        f"1. Differential diagnosis (possible causes)\n"
        f"2. Common OTC medications (avoid prescriptions)\n"
        f"3. Home/lifestyle measures\n"
        f"4. Red flags requiring urgent care\n"
        f"5. Strong disclaimer that this is for educational purposes only\n\n"
        f"Use clear headings and bullet points. Base your suggestions on symptom timing, severity, and history."
    )

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a cautious, educational AI medical assistant."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.6
    )
    return response['choices'][0]['message']['content']

# Route for main form submission
@app.route("/", methods=["GET", "POST"])
def index():
    summary_response = ""
    if request.method == "POST":
        symptoms = request.form.get("symptoms", "")
        context = {
            "age_range": request.form.get("age_range", "unknown"),
            "sex": request.form.get("sex", "unknown"),
            "existing_conditions": request.form.get("existing_conditions", "unknown"),
            "allergies": request.form.get("allergies", "unknown"),
            "medications": request.form.get("medications", "unknown"),
            "onset": request.form.get("onset", "unknown"),
            "better": request.form.get("better", "unknown"),
            "worse": request.form.get("worse", "unknown"),
            "severity": request.form.get("severity", "unknown"),
            "treatments": request.form.get("treatments", "unknown")
        }
        try:
            summary_response = ask_chatgpt(symptoms, context)
        except Exception as e:
            summary_response = f"⚠️ Error: {str(e)}"

    return render_template("index.html", response=summary_response)

# Route for follow-up questions
@app.route("/followup", methods=["POST"])
def followup():
    followup_question = request.form.get("followup", "")
    followup_response = ""
    try:
        reply = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": "You are a careful and educational AI assistant for medical Q&A."
                },
                {
                    "role": "user",
                    "content": f"A patient has a follow-up question:\n\n{followup_question}\n\nPlease respond clearly, briefly, and include a strong disclaimer that this is educational only."
                }
            ],
            temperature=0.6
        )
        followup_response = reply['choices'][0]['message']['content']
    except Exception as e:
        followup_response = f"⚠️ Error: {str(e)}"

    return render_template("index.html", response=None, followup_response=followup_response)

# Run the app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000, debug=True)