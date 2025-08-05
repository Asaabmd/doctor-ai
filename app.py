from flask import Flask, render_template, request, make_response
import openai
import os

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

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
    return response['choices'][0]['message']['content']


@app.route("/", methods=["GET", "POST"])
def index():
    if request.args.get("access") == "granted":
        resp = make_response(render_template("index.html", response="", use_count=0))
        resp.set_cookie("access_granted", "true", max_age=60 * 60 * 24 * 365)
        resp.set_cookie("use_count", "0", max_age=60 * 60 * 24 * 30)
        return resp

    has_access = request.cookies.get("access_granted") == "true"
    use_count = int(request.cookies.get("use_count", 0))
    locked_message = "🔒 This free version allows only one summary. Please subscribe for unlimited access."

    # POST — new submission
    if request.method == "POST":
        form_use_count = int(request.form.get("use_count", 0))
        if not has_access and (use_count >= 1 or form_use_count >= 1):
            return render_template("index.html", response=locked_message, use_count=use_count)

        symptoms = request.form.get("symptoms", "")
        context = {
            "age_range": request.form.get("age_range", "skip"),
            "sex": request.form.get("sex", "skip"),
            "existing_conditions": request.form.get("existing_conditions", "skip"),
            "allergies": request.form.get("allergies", "skip"),
            "medications": request.form.get("medications", "skip"),
            "onset": request.form.get("onset", "unknown"),
            "better": request.form.get("better", "unknown"),
            "worse": request.form.get("worse", "unknown"),
            "severity": request.form.get("severity", "unknown"),
            "treatments": request.form.get("treatments", "unknown")
        }

        try:
            output = ask_chatgpt(symptoms, context)
        except Exception as e:
            output = f"⚠️ Error: {e}"

        new_use_count = use_count + 1
        resp = make_response(render_template("index.html", response=output, use_count=new_use_count))
        if not has_access:
            resp.set_cookie("use_count", str(new_use_count), max_age=60 * 60 * 24 * 30)
        return resp

    # First visit or after blocking
    if not has_access and use_count >= 1:
        return render_template("index.html", response=locked_message, use_count=use_count)

    return render_template("index.html", response="", use_count=use_count)


@app.route("/followup", methods=["POST"])
def followup():
    followup_question = request.form.get("followup", "")
    try:
        reply = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a careful and informative AI doctor. Clarify medical questions in a safe, educational manner."},
                {"role": "user", "content": f"A patient has a follow-up question:\n\n{followup_question}\n\nPlease answer clearly and briefly, and remind them this is educational only."}
            ],
            temperature=0.6
        )
        followup_response = reply['choices'][0]['message']['content']
    except Exception as e:
        followup_response = f"⚠️ Error: {e}"
    return render_template("index.html", response=followup_response, use_count=request.cookies.get("use_count", 0))