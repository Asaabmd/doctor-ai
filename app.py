from flask import Flask, request, render_template, make_response
import openai
import os

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# Main summary generation with full medical context
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
        f"Use clear headings and bullet points. Consider timing, severity, and prior treatments."
    )

    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a cautious, educational AI medical assistant. Avoid treatment or diagnostic claims."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.6
    )
    return response.choices[0].message.content

# Route: Home
@app.route("/", methods=["GET", "POST"])
def index():
    # Step 1: Handle ?access=granted from Payhip link
    if request.args.get("access") == "granted":
        resp = make_response(render_template("index.html", response=""))
        resp.set_cookie("access_granted", "true", max_age=60 * 60 * 24 * 365)  # 1 year
        return resp

    access_granted = request.cookies.get("access_granted")
    session_count = int(request.cookies.get("session_count", 0))

    if request.method == "POST":
        # Gather inputs
        symptoms = request.form.get("symptoms", "")
        context = {
            "age_range": request.form.get("age_range", ""),
            "sex": request.form.get("sex", ""),
            "existing_conditions": request.form.get("existing_conditions", ""),
            "allergies": request.form.get("allergies", ""),
            "medications": request.form.get("medications", ""),
            "onset": request.form.get("onset", ""),
            "better": request.form.get("better", ""),
            "worse": request.form.get("worse", ""),
            "severity": request.form.get("severity", ""),
            "treatments": request.form.get("treatments", "")
        }

        try:
            if access_granted == "true":
                # Unlimited access after Payhip
                output = ask_chatgpt(symptoms, context)
                return render_template("index.html", response=output)

            elif session_count < 1:
                # First free use
                output = ask_chatgpt(symptoms, context)
                resp = make_response(render_template("index.html", response=output))
                resp.set_cookie("session_count", "1", max_age=60 * 60 * 24 * 30)  # 30 days
                return resp

            else:
                # Limit reached
                return render_template("index.html", response="⚠️ Free use limit reached. Please [subscribe for unlimited access](https://payhip.com/b/Da82I).")

        except Exception as e:
            return render_template("index.html", response=f"⚠️ Error: {e}")

    return render_template("index.html", response="")

# Route: Follow-up question
@app.route("/followup", methods=["POST"])
def followup():
    followup_question = request.form.get("followup", "")
    try:
        prompt = (
            f"A patient has a follow-up question:\n\n{followup_question}\n\n"
            f"Please answer clearly and briefly. Remind them this is for educational purposes only."
        )
        reply = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a careful and informative AI doctor. Clarify medical questions safely and clearly."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.6
        )
        return render_template("index.html", response=reply.choices[0].message.content)
    except Exception as e:
        return render_template("index.html", response=f"⚠️ Error: {e}")

# Run the app
if __name__ == "__main__":
    app.run(debug=True)