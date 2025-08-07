from flask import Flask, render_template, request, jsonify, make_response
import openai
import json
import os

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# Load subscriptions from JSON file
def load_subscriptions():
    try:
        with open("subscriptions.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

# Save usage flag in response cookie
def save_usage_cookie(response, used_summary=False, used_followup=False):
    response.set_cookie("used_summary", "true" if used_summary else "false")
    response.set_cookie("used_followup", "true" if used_followup else "false")

# Check if user has already used free summary/follow-up
def has_used(request):
    return (
        request.cookies.get("used_summary") == "true",
        request.cookies.get("used_followup") == "true"
    )

# Home page with form
@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

# Handle form submission
@app.route("/", methods=["POST"])
def generate_summary():
    email = request.form.get("email", "").strip().lower()
    subscriptions = load_subscriptions()
    is_subscribed = subscriptions.get(email) in ["active", "manual"]

    used_summary, _ = has_used(request)

    if not is_subscribed and used_summary:
        return make_response("Free summary already used. Please subscribe for unlimited access.", 403)

    user_input = {
        "Symptoms": request.form.get("symptoms", ""),
        "Existing conditions": request.form.get("conditions", ""),
        "Allergies": request.form.get("allergies", ""),
        "Medications": request.form.get("medications", ""),
        "Onset": request.form.get("onset", ""),
        "What makes it better": request.form.get("better", ""),
        "What makes it worse": request.form.get("worse", ""),
        "Severity": request.form.get("severity", ""),
        "What has been tried": request.form.get("tried", "")
    }

    prompt = "Generate a friendly, easy-to-understand summary based on this information:\n"
    for key, value in user_input.items():
        prompt += f"{key}: {value}\n"

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800
        )
        summary = response['choices'][0]['message']['content'].strip()
    except Exception as e:
        return make_response(f"Error generating summary: {e}", 500)

    resp = make_response(render_template("index.html", summary=summary, show_modal=True, email=email, subscribed=is_subscribed))
    if not is_subscribed:
        save_usage_cookie(resp, used_summary=True)
    return resp

# Handle follow-up question
@app.route("/followup", methods=["POST"])
def followup():
    data = request.json
    email = data.get("email", "").strip().lower()
    question = data.get("question", "")
    previous_summary = data.get("summary", "")

    subscriptions = load_subscriptions()
    is_subscribed = subscriptions.get(email) in ["active", "manual"]
    _, used_followup = has_used(request)

    if not is_subscribed and used_followup:
        return jsonify({"error": "limit_reached"})

    prompt = f"This was the summary given:\n{previous_summary}\n\nUser's follow-up question: {question}\n\nProvide a helpful educational response."

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=600
        )
        reply = response['choices'][0]['message']['content'].strip()
    except Exception as e:
        return jsonify({"error": f"OpenAI error: {str(e)}"})

    resp = jsonify({"response": reply})
    if not is_subscribed:
        save_usage_cookie(resp, used_followup=True)
    return resp

# Webhook for Payhip (optional for later use)
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.json
    event = data.get("event")
    email = data.get("data", {}).get("email", "").strip().lower()
    if not email:
        return "No email", 400

    subscriptions = load_subscriptions()

    if event in ["subscription.created", "product.purchased"]:
        subscriptions[email] = "active"
    elif event in ["subscription.deleted", "subscription.cancelled"]:
        subscriptions[email] = "inactive"

    with open("subscriptions.json", "w") as f:
        json.dump(subscriptions, f, indent=2)

    return "OK", 200

if __name__ == "__main__":
    app.run(debug=True)