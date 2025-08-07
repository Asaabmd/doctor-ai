from flask import Flask, render_template, request, make_response, jsonify
import openai
import os
import json

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")
SUBSCRIPTION_FILE = "subscriptions.json"

# 🔄 Helper to check subscription status
def is_subscribed(email: str) -> bool:
    try:
        with open(SUBSCRIPTION_FILE, "r") as f:
            data = json.load(f)
        return data.get(email, "").lower() in ["active", "manual"]
    except Exception:
        return False

# 🤖 Generate summary from ChatGPT
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

# 🌐 Homepage
@app.route("/", methods=["GET", "POST"])
def index():
    email = request.cookies.get("email")
    has_access = request.cookies.get("access_granted") == "true"
    use_count = int(request.cookies.get("use_count", 0))

    if request.args.get("access") == "granted":
        resp = make_response(render_template("index.html", response="", use_count=use_count))
        resp.set_cookie("access_granted", "true", max_age=60 * 60 * 24 * 365)
        return resp

    if not (has_access or is_subscribed(email or "")) and use_count >= 1 and request.method == "POST":
        return render_template("index.html", response="🔒 This free version allows only one summary and one follow-up. Please subscribe for unlimited access.", use_count=use_count)

    output = ""
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
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
            "treatments": request.form.get("treatments", "unknown"),
        }

        try:
            output = ask_chatgpt(symptoms, context)
        except Exception as e:
            output = f"⚠️ Error: {e}"

        resp = make_response(render_template("index.html", response=output, use_count=use_count + 1))
        resp.set_cookie("email", email, max_age=60 * 60 * 24 * 365)
        if not (has_access or is_subscribed(email)):
            resp.set_cookie("use_count", str(use_count + 1), max_age=60 * 60 * 24 * 30)
        return resp

    return render_template("index.html", response=output, use_count=use_count)

# ➕ Follow-up route
@app.route("/followup", methods=["POST"])
def followup():
    email = request.cookies.get("email")
    has_access = request.cookies.get("access_granted") == "true"
    use_count = int(request.cookies.get("use_count", 0))

    if not (has_access or is_subscribed(email or "")) and use_count >= 2:
        return render_template("index.html", response="🔒 You’ve reached the free follow-up limit. Please subscribe to ask more questions.", use_count=use_count)

    question = request.form.get("followup", "")
    try:
        reply = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are a careful and informative AI doctor. Clarify medical questions in a safe, educational manner."},
                {"role": "user", "content": f"A patient has a follow-up question:\n\n{question}\n\nPlease answer clearly and briefly, and remind them this is educational only."}
            ],
            temperature=0.6
        )
        followup_response = reply['choices'][0]['message']['content']
    except Exception as e:
        followup_response = f"⚠️ Error: {e}"

    resp = make_response(render_template("index.html", response=followup_response, use_count=use_count + 1))
    if not (has_access or is_subscribed(email)):
        resp.set_cookie("use_count", str(use_count + 1), max_age=60 * 60 * 24 * 30)
    return resp

# ✅ Webhook to update subscriptions.json
@app.route("/webhook", methods=["POST"])
def webhook():
    event = request.get_json()
    if not event or "event_name" not in event or "email" not in event:
        return jsonify({"status": "ignored", "reason": "missing event_name or email"}), 400

    event_type = event.get("event_name", "").lower()
    email = event.get("email", "").strip().lower()

    try:
        with open(SUBSCRIPTION_FILE, "r") as f:
            data = json.load(f)
    except FileNotFoundError:
        data = {}

    if event_type in ["subscription.created", "paid"]:
        data[email] = "active"
    elif event_type in ["subscription.deleted", "refunded"]:
        data[email] = "inactive"

    with open(SUBSCRIPTION_FILE, "w") as f:
        json.dump(data, f, indent=2)

    return jsonify({"status": "success", "email": email, "event": event_type}), 200

# 🚀 Run the app
if __name__ == "__main__":
    app.run(debug=True)