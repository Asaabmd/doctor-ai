from flask import Flask, render_template, request, redirect, url_for, session, make_response
summary = ask_chatgpt_summary(symptoms, context)
print("✅ Summary generated successfully.")
except Exception as e:
summary = f"⚠️ Error generating summary: {e}"
print("❌ Error in summary generation:", e)


session["summary"] = summary
session["email"] = email
session["use_count"] = use_count + 1


resp = redirect(url_for("summary_page"))
resp.set_cookie("email", email, max_age=60 * 60 * 24 * 365)
if not (has_access or is_subscribed(email)):
resp.set_cookie("use_count", str(use_count + 1), max_age=60 * 60 * 24 * 30)
return resp


return render_template("index.html", response="", followup_response="", use_count=use_count)


@app.route("/summary", methods=["GET", "POST"])
def summary_page():
summary = session.get("summary", "")
email = session.get("email", "").strip().lower()
use_count = session.get("use_count", 0)
has_access = request.cookies.get("access_granted") == "true"
followup_answer = ""
is_subscribed_user = has_access or is_subscribed(email)


if not summary:
print("⚠️ No summary in session. Redirecting to home.")
return redirect(url_for("index"))


if request.method == "POST":
if not is_subscribed_user and use_count >= 2:
followup_answer = "🔒 You’ve reached the free follow-up limit. Please subscribe to ask more questions."
else:
question = request.form.get("followup", "").strip()
if not question:
followup_answer = "⚠️ Please enter a follow-up question."
else:
try:
followup_answer = ask_chatgpt_followup(question, summary)
session["use_count"] = use_count + 1
except Exception as e:
followup_answer = f"⚠️ Error generating follow-up: {e}"
print("❌ Follow-up error:", e)


return render_template("summary.html", response=summary, followup_response=followup_answer, is_subscribed=is_subscribed_user)


@app.route("/webhook", methods=["POST"])
def webhook():
event = request.json
email = event.get("email", "").strip().lower()
event_type = event.get("event")


try:
with open(SUBSCRIPTIONS_FILE, "r") as f:
subs = json.load(f)
except:
subs = {}


if event_type in ["subscription.created", "subscription.updated", "subscription.paid"]:
subs[email] = {"status": "active"}
elif event_type in ["subscription.deleted", "subscription.refunded"]:
subs[email] = {"status": "inactive"}


with open(SUBSCRIPTIONS_FILE, "w") as f:
json.dump(subs, f)


return "", 200


if __name__ == "__main__":
app.run(debug=True)