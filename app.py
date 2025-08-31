from flask import Flask, render_template, request, redirect, url_for
Patient is experiencing the following symptoms:
{data['symptoms']}


Existing conditions: {data['existing_conditions']}
Allergies: {data['allergies']}
Medications: {data['medications']}
Symptom onset: {data['onset']}
What makes it better: {data['better']}
What makes it worse: {data['worse']}
Severity: {data['severity']}
Treatments tried: {data['treatments']}
Age range: {data['age_range']}
Sex: {data['sex']}


Based on this, provide an educational and personalized summary including possible causes, over-the-counter treatment, home remedies, and when to seek medical attention. Do not give specific diagnoses or prescriptions.
"""


response = openai.ChatCompletion.create(
model="gpt-4",
messages=[
{"role": "system", "content": "You are an educational medical assistant, not a doctor."},
{"role": "user", "content": prompt}
]
)
return response.choices[0].message.content


def generate_followup(original_summary, followup_question):
prompt = f"""
Based on this summary:
{original_summary}


Answer this follow-up question:
{followup_question}


Keep the answer short, educational, and general.
"""


response = openai.ChatCompletion.create(
model="gpt-4",
messages=[
{"role": "system", "content": "You are a helpful health explainer."},
{"role": "user", "content": prompt}
]
)
return response.choices[0].message.content


@app.route('/', methods=['GET', 'POST'])
def index():
if request.method == 'POST':
email = request.form['email'].strip().lower()
form_data = request.form.to_dict()
subscribed = is_subscribed(email)
already_used = has_used(email)


if not subscribed and already_used:
return render_template('index.html', error="You've already used your free session.", subscribed=False)


summary = generate_summary(form_data)


if not subscribed:
mark_used(email)


return render_template('index.html', response=summary, email=email, subscribed=subscribed)


return render_template('index.html')


@app.route('/followup', methods=['POST'])
def followup():
email = request.form.get('email', '').strip().lower()
original = request.form['original_summary']
question = request.form['followup']
answer = generate_followup(original, question)
subscribed = is_subscribed(email)


return render_template('index.html', response=original, followup_response=answer, email=email, subscribed=subscribed)


@app.route('/webhook', methods=['POST'])
def webhook():
data = request.get_json()
email = data.get('email', '').strip().lower()
status = data.get('status', 'inactive')


if email:
subs = load_json(SUB_FILE)
subs[email] = {'status': status}
save_json(SUB_FILE, subs)


return '', 200


if __name__ == '__main__':
app.run(debug=True)