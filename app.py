from flask import Flask, render_template, request, make_response, jsonify
import openai
import os
import json

app = Flask(__name__)
openai.api_key = os.getenv("OPENAI_API_KEY")

# ---- CONFIG ----
SUBSCRIPTION_FILE = "subscriptions.json"
SUBSCRIBE_URL = "https://payhip.com/order?link=Da82I&pricing_plan=Q7zqKb9ZGg"  # update if you change plans

# ---- HELPERS ----
def is_subscribed(email: str) -> bool:
    """Return True if email is active/manually granted in subscriptions.json."""
    if not email:
        return False
    try:
        with open(SUBSCRIPTION_FILE, "r") as f:
            data = json.load(f)
        return data.get(email.lower(), "").lower() in ["active", "manual"]
    except Exception:
        return False

def ask_chatgpt(symptoms: str, context: dict) -> str:
    """Call GPT to generate the educational summary."""
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
        "2) Common OTC medications (avoid Rx)\n"
        "3) Helpful home/lifestyle measures\n"
        "4) Red flags requiring urgent care\n"
        "5) A strong disclaimer that this is educational only\n\n"
        "Use clear headings and bullet points. Consider timing, severity, and prior treatments."
    )

    resp = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[
            {"role": "system",
             "content": "You are a cautious, educational AI medical assistant. Avoid treatment or diagnostic claims."},
            {"role": "user", "content": prompt}
        ],
        temperature=0.6
    )
    return resp["choices"][0]["message"]["content"]

# ---- ROUTES ----
@app.route("/", methods=["GET", "POST"])
def index():
    # Recognize Payhip redirect (?access=granted) and set long-lived cookie
    if request.args.get("access") == "granted":
        resp = make_response(render_template("index.html",
                                             response="",
                                             modal_shown=False,
                                             show_subscribe_banner=False,
                                             subscribe_url=SUBSCRIBE_URL,
                                             use_count=0))
        resp.set_cookie("access_granted", "true", max_age=60 * 60 * 24 * 365)  # 1 year
        return resp

    # Read cookies
    has_access = request.cookies.get("access_granted") == "true"
    use_count = int(request.cookies.get("use_count", 0))
    cookie_email = (request.cookies.get("email") or "").strip().lower()

    # Determine subscription status
    subscribed = has_access or is_subscribed(cookie_email)

    # If form submitted
    if request.method == "POST":
        # Pull form data
        email = (request.form.get("email") or "").strip().lower()
        symptoms = request.form.get("symptoms", "").strip()

        context = {
            "existing_conditions": request.form.get("existing_conditions", "").strip(),
            "allergies": request.form.get("allergies", "").strip(),
            "medications": request.form.get("medications", "").strip(),
            "onset": request.form.get("onset", "").strip(),
            "better": request.form.get("better", "").strip(),
            "worse": request.form.get("worse", "").strip(),
            "severity": request.form.get("severity", "").strip(),
            "treatments": request.form.get("treatments", "").strip(),
            "age_range": request.form.get("age_range", "").strip(),
            "sex": request.form.get("sex", "").strip(),
        }

        # Re-evaluate subscription with latest email
        subscribed = subscribed or is_subscribed(email)

        # Enforce 1 summary if not subscribed
        if not subscribed and use_count >= 1:
            # Already used free summary; block further summaries
            return render_template(
                "index.html",
                response=("🔒 This free version allows one summary and one follow-up. "
                          "Subscribe below for unlimited access."),
                modal_shown=True,  # show modal with the lock text so it's obvious
                show_subscribe_banner=True,
                subscribe_url=SUBSCRIBE_URL,
                use_count=use_count
            )

        # Generate summary
        try:
            summary = ask_chatgpt(symptoms, context)
        except Exception as e:
            summary = f"⚠️ Error: {e}"

        # Build response
        resp = make_response(render_template(
            "index.html",
            response=summary,
            modal_shown=True,  # pop the modal automatically
            show_subscribe_banner=(not subscribed),
            subscribe_url=SUBSCRIBE_URL,
            use_count=(use_count + (0 if subscribed else 1))  # count summary if free user
        ))

        # Persist cookies (email for matching subscription; use_count for free users)
        if email:
            resp.set_cookie("email", email, max_age=60 * 60 * 24 * 365)
        if not subscribed:
            resp.set_cookie("use_count", str(use_count + 1), max_age=60 * 60 * 24 * 30)

        return resp

    # GET request (initial load)
    return render_template(
        "index.html",
        response="",
        modal_shown=False,
        show_subscribe_banner=(not (has_access or is_subscribed(cookie_email))),
        subscribe_url=SUBSCRIBE_URL,
        use_count=use_count
    )

@app.route("/followup", methods=["POST"])
def followup():
    has_access = request.cookies.get("access_granted") == "true"
    use_count = int(request.cookies.get("use_count", 0))
    email = (request.cookies.get("email") or "").strip().lower()
    subscribed = has_access or is_subscribed(email)

    # Enforce follow-up limit for free users (1 follow-up → second use)
    if not subscribed and use_count >= 2:
        return render_template(
            "index.html",
            response=("🔒 You’ve reached the free follow-up limit. "
                      "Subscribe below for unlimited questions."),
            modal_shown=True,
            show_subscribe_banner=True,
            subscribe_url=SUBSCRIBE_URL,
            use_count=use_count
        )

    question = request.form.get("followup", "").strip()

    try:
        reply = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system",
                 "content": "You are a careful and informative AI doctor. Clarify medical questions in a safe, educational manner."},
                {"role": "user",
                 "content": f"A patient has a follow-up question:\n\n{question}\n\n"
                            "Please answer clearly and briefly, and remind them this is educational only."}
            ],
            temperature=0.6
        )
        followup_text = reply["choices"][0]["message"]["content"]
    except Exception as e:
        followup_text = f"⚠️ Error: {e}"

    resp = make_response(render_template(
        "index.html",
        response=followup_text,
        modal_shown=True,
        show_subscribe_banner=(not subscribed),
        subscribe_url=SUBSCRIBE_URL,
        use_count=(use_count + (0 if subscribed else 1))
    ))

    if not subscribed:
        resp.set_cookie("use_count", str(use_count + 1), max_age=60 * 60 * 24 * 30)

    return resp

# Optional webhook if you wire up Payhip to auto-update subscriptions.json
@app.route("/webhook", methods=["POST"])
def webhook():
    event = request.get_json(force=True, silent=True) or {}
    event_type = (event.get("event_name") or "").lower()
    email = (event.get("email") or "").strip().lower()
    if not email or not event_type:
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

    return jsonify({"status": "ok", "email": email, "event": event_type}), 200

if __name__ == "__main__":
    app.run(debug=True)