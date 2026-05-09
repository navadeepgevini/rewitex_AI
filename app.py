from flask import Flask, request, jsonify, render_template, session, redirect, url_for, flash
import os
from groq import Groq
from dotenv import load_dotenv
import json
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from db import db, User

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-key-please-change")

# Database Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///rewritex.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

# Login Manager Configuration
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login_page'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create database tables
with app.app_context():
    db.create_all()


client = Groq(api_key=os.getenv("GROQ_API_KEY"))
MODEL_ID = "llama-3.3-70b-versatile"


def lang_code_to_name(code):
    mapping = {
        "en": "English",
        "hi": "Hindi",
        "ta": "Tamil",
        "kn": "Kannada",
        "mr": "Marathi",
        "gu": "Gujarati",
        "ml": "Malayalam",
        "te": "Telugu",
        "or": "Odia",
        "fr": "French",
        "de": "German",
        "es": "Spanish",
        "pt": "Portuguese",
        "zh": "Chinese",
        "auto": "auto-detect"
    }
    return mapping.get(code, code)


def build_prompt(user_message, modes, freeze_words, source_lang, target_lang, tone=None, audience=None, goal=None, translate_only=False):
    # Handle initial friendly response
    if user_message.strip().lower() == "hi" and not translate_only:
        return "Hi there! How can I help you today?"

    instructions = []
    
    if "formal" in modes or (tone == "formal"):
        instructions.append("Adopt a formal, professional tone.")
    if "informal" in modes:
        instructions.append("Adopt a casual, friendly, and approachable tone.")
    if "seo" in modes:
        instructions.append("Optimize the text for Search Engine Optimization naturally.")
    if "humanize" in modes:
        instructions.append("Make the text sound highly natural and human-written, avoiding AI-like cliches.")
    if "summarize" in modes:
        instructions.append("Provide a clear and concise summary of the main points.")

    if tone and audience and goal:
        audience_desc = {
            "Academic Professor": "Use complex terminology, cite broad concepts if relevant, and maintain an objective stance.",
            "Potential Investor": "Use confident, visionary language. Emphasize metrics such as ROI and market size.",
            "Blog Readers": "Use highly engaging, accessible language with relatable examples.",
            "Technical Team": "Use precise, unambiguous technical language focusing on clarity, logic, and correctness."
        }.get(audience, "")
        goal_desc = {
            "To Persuade": "Focus on convincing and motivating the reader to take action.",
            "To Inform": "Focus purely on delivering clear and factual information.",
            "To Build Rapport": "Focus on establishing a friendly, trustworthy, and empathetic connection."
        }.get(goal, "")
        
        if audience_desc or goal_desc:
            instructions.append(f"Tailor the text for a {tone} tone targeting an audience of '{audience}' with the goal '{goal}'. {audience_desc} {goal_desc}")

    if freeze_words:
        instructions.append(f"CRITICAL: Do absolutely NOT change, replace, or translate the following keywords: [{freeze_words}]. Preserve them exactly as they appear.")

    t_name = lang_code_to_name(target_lang)
    s_name = lang_code_to_name(source_lang)
    
    if target_lang != "auto" and target_lang != source_lang:
        instructions.append(f"Provide the final output exclusively in {t_name}.")

    if translate_only:
        return f"""
Your ONLY task is to translate the provided text into {t_name}. Do not add any explanations, notes, or conversational filler.
Return exactly the translated text and nothing else.

Text: {user_message}
"""

    history = session.get('conversation_history', [])
    context = "\n".join([f"User: {u}\nAI: {a}" for u, a in history[-3:]])

    formatted_instructions = "\n".join([f"- {i}" for i in instructions])

    prompt = f"""
You are RewriteX AI, an elite, professional multilingual writing assistant. 
Your task is to rewrite the user's text according to the following strict instructions:
{formatted_instructions}

Do NOT include any conversational filler (e.g., "Here is the rewritten text:", "Sure!"). Return ONLY the final output.

## Previous Conversation Context:
{context}

## User Input to Process:
{user_message}
"""
    return prompt


@app.route('/')
@login_required
def home():
    return render_template('index.html')

@app.route('/login')
def login_page():
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    return render_template('login.html')

@app.route('/api/auth/register', methods=['POST'])
def register():
    data = request.get_json()
    name = data.get('name', '').strip()
    email = data.get('email', '').strip()
    password = data.get('password', '')

    if not name or not email or not password:
        return jsonify({"error": "Missing required fields"}), 400

    if User.query.filter_by(email=email).first():
        return jsonify({"error": "Email already registered"}), 400

    new_user = User(name=name, email=email)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()

    return jsonify({"success": True}), 201

@app.route('/api/auth/login', methods=['POST'])
def login():
    data = request.get_json()
    email = data.get('email', '').strip()
    password = data.get('password', '')
    remember = data.get('remember', False)

    user = User.query.filter_by(email=email).first()

    if user and user.check_password(password):
        login_user(user, remember=remember)
        return jsonify({"success": True}), 200

    return jsonify({"error": "Invalid email or password"}), 401

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login_page'))


@app.route('/api', methods=['POST'])
@login_required
def api_reply():
    data = request.get_json()

    user_message = data.get("message", "").strip()
    modes = data.get("modes", [])
    freeze_words = data.get("freeze", "")
    source_lang = data.get("source_lang", "auto")
    target_lang = data.get("target_lang", "en")
    tone = data.get("tone", None)
    audience = data.get("audience", None)
    goal = data.get("goal", None)
    translate_only = data.get("translate_only", False)

    if not user_message:
        return jsonify({"error": "Empty message"}), 400

    # Quick greet response without API call
    if user_message.lower() == "hi" and not translate_only:
        greeting = "Hi there! How can I help you today?"
        history = session.get('conversation_history', [])
        history.append((user_message, greeting))
        session['conversation_history'] = history
        return jsonify({"reply": greeting})

    try:
        prompt = build_prompt(user_message, modes, freeze_words, source_lang, target_lang, tone, audience, goal, translate_only)

        # If built prompt is just a short translate or greeting, bypass prompt intro
        if translate_only:
            completion = client.chat.completions.create(
                model=MODEL_ID,
                messages=[{"role": "user", "content": prompt}]
            )
            ai_reply = completion.choices[0].message.content.strip()
        elif prompt.startswith("Hi there!"):
            ai_reply = prompt
        else:
            completion = client.chat.completions.create(
                model=MODEL_ID,
                messages=[{"role": "user", "content": prompt}]
            )
            ai_reply = completion.choices[0].message.content.strip()

        history = session.get('conversation_history', [])
        history.append((user_message, ai_reply))
        session['conversation_history'] = history
        return jsonify({"reply": ai_reply})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route('/analyze', methods=['POST'])
@login_required
def analyze_text():
    data = request.get_json()
    text = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "No text"}), 400

    try:
        import re
        prompt = f"""
        Analyze the following text and provide ONLY a valid JSON response with these exact fields:
        "score": A number between 0-100 indicating overall quality.
        "readability": One of "Excellent", "Good", "Needs Improvement".
        "grade_level": The estimated grade level (e.g., "6th Grade", "College").
        "grammar_issues": The estimated number of grammar or style issues found.
        "suggestions": A list of 1-3 specific, actionable suggestions to improve the text (max 10 words each).

        Do not add any text before or after the JSON.
        
        Text: {text}
        """
        completion = client.chat.completions.create(
            model=MODEL_ID,
            messages=[{"role": "user", "content": prompt}]
        )
        text_resp = completion.choices[0].message.content.strip()
        
        # Try to find JSON block using regex if there's markdown formatting
        json_match = re.search(r'```(?:json)?\s*({.*?})\s*```', text_resp, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            # Fallback to the raw text
            json_str = text_resp
            
        analysis = json.loads(json_str)
        
        return jsonify(analysis)
    except Exception as e:
        # Fallback to simple calculation if AI fails
        words = len(text.split())
        grammar_issues = max(0, (words // 80) - 1)
        score = min(100, max(50, 100 - grammar_issues * 2))
        readability = "Excellent" if score > 85 else "Good" if score > 65 else "Needs Improvement"
        grade = "Intermediate" if words < 150 else "Advanced"
        
        return jsonify({
            "score": score,
            "readability": readability,
            "grade_level": grade,
            "grammar_issues": grammar_issues,
            "fallback": True
        })


if __name__ == '__main__':
    app.run(debug=True)
