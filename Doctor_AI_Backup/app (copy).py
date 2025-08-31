from flask import Flask, render_template, request, make_response, jsonify
import openai
import os
import json

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

SUBSCRIPTION_FILE = "subscriptions.json"

# ----------------------
# Helpers
# ----------------------
def is_subscribed(email: str) -> bool:
    """Check if the user is subscribed based on subscriptions.json."""
    try:
        with open(SUBSCRIPTION_FILE, "r") as f:
            data = json.load(f)
        return data.get(email, "").lower() in ["active", "manual", "true", "yes"]
    except Exception:
        return False


def ask_chatgpt_summary(symptoms: str, context: dict) -> str:
    """Generate a personalized educational summary."""
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
        f"Treatments Tried: {context.get('treatments', 'unknown')}",
    ])

    prompt = (
        "You are a board-certified family medicine physician writing an educational summary.\n\n"
        f"Patient profile and HPI:\n{context_summary}\n\n"
        f"Reported symptoms:\n{symptoms}\n\n"
        "Please include:\n"
        "1) Differential diagnosis (possible causes)\n"
        "2) Common OTC options (avoid prescription meds)\n"
        "3) Home/lifestyle measures\n"
        "4) Red flags that require urgent care\n"
        "5) A strong disclaimer that this is educational only, not medical advice\n\n"
        "Use clear headings and bullet points. Be concise and readable for patients."
    )

    # If you’re on a newer OpenAI lib/API, swap for the appropriate chat call.
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a cautious, educational AI medical assistant. Avoid diagnosis or treatment guarantees."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.6,
    )
    return response["choices"][0]["message"]["content"]


def ask_chatgpt_followup(question: str) -> str:
    """Generate an educational follow-up answer."""
    response = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a careful and informative AI doctor. Clarify medical questions in a safe, educational manner."},
            {"role": "user", "content": f"A patient asks a follow-up question:\n\n{question}\n\nAnswer briefly and clearly, and remind them this is educational only."}
        ],
        temperature=0.6,
    )
    return response["choices"][0]["message"]["content"]


# ----------------------
# Routes
# ----------------------
@app.route("/", methods=["GET", "POST"])
def index():
    email = (request.cookies.get("email") or "").strip().lower()
    has_access = request.cookies.get("access_granted") == "true"
    use_count = int(request.cookies.get("use_count", 0))

    summary = ""
    followup_answer = ""
    show_modal = False

    if request.method == "POST":
        # Free limit: 1 summary + 1 follow-up total (2 uses)
        # First POST to "/" is the summary (use 1)
        if not (has_access or is_subscribed(email)) and use_count >= 1:
            # Already consumed the free summary
            return render_template(
                "index.html",
                response="🔒 This free version allows only one summary and one follow-up. Please subscribe for unlimited access.",
                followup_response="",
                use_count=use_count,
                show_modal=True,
            )

        # Gather form fields
        email = (request.form.get("email") or "").strip().lower()
        symptoms = request.form.get("symptoms", "").strip()

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
            summary = ask_chatgpt_summary(symptoms, context)
            show_modal = True
        except Exception as e:
            summary = f"⚠️ Error generating summary: {e}"
            show_modal = True

        # Render + set cookies
        resp = make_response(render_template(
            "index.html",
            response=summary,
            followup_response="",
            use_count=use_count + 1,
            show_modal=show_modal,
        ))
        # Persist email for subscription checks
        resp.set_cookie("email", email, max_age=60 * 60 * 24 * 365)  # 1 year
        if not (has_access or is_subscribed(email)):
            resp.set_cookie("use_count", str(use_count + 1), max_age=60 * 60 * 24 * 30)  # 30 days
        return resp

    # GET
    return render_template(
        "index.html",
        response=summary,
        followup_response=followup_answer,
        use_count=use_count,
        show_modal=show_modal,
    )


@app.route("/followup", methods=["POST"])
def followup():
    email = (request.cookies.get("email") or "").strip().lower()
    has_access = request.cookies.get("access_granted") == "true"
    use_count = int(request.cookies.get("use_count", 0))

    # Keep the original summary that was shown
    original_summary = request.form.get("original_summary", "")

    # Free limit: summary (use 1) + follow-up (use 2)
    if not (has_access or is_subscribed(email)) and use_count >= 2:
        return render_template(
            "index.html",
            response=original_summary,
            followup_response="🔒 You’ve reached the free follow-up limit. Please subscribe to ask more questions.",
            use_count=use_count,
            show_modal=True,
        )

    question = request.form.get("followup", "").strip()
    try:
        followup_answer = ask_chatgpt_followup(question)
    except Exception as e:
        followup_answer = f"⚠️ Error generating follow-up: {e}"

    resp = make_response(render_template(
        "index.html",
        response=original_summary,
        followup_response=followup_answer,
        use_count=use_count + 1,
        show_modal=True,
    ))
    if not (has_access or is_subscribed(email)):
        resp.set_cookie("use_count", str(use_count + 1), max_age=60 * 60 * 24 * 30)
    return resp


@app.route("/webhook", methods=["POST"])
def webhook():
    """
    Payhip webhook endpoint.
    Expect JSON like:
      {
        "event_name": "subscription.created" | "subscription.deleted" | "paid" | "refunded",
        "email": "user@example.com",
        ...
      }
    """
    event = request.get_json(silent=True) or {}
    event_type = (event.get("event_name") or "").lower()
    email = (event.get("email") or "").strip().lower()

    if not event_type or not email:
        return jsonify({"status": "ignored", "reason": "missing event_name or email"}), 400

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


if __name__ == "__main__":
    # Replit will typically run with its own server runner; debug=True for dev
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=True)