# pyrefly: ignore [missing-import]
from flask import Flask, render_template, request, jsonify, session
import os, webbrowser, datetime, smtplib, subprocess, requests
from email.mime.text import MIMEText
import time
import sqlite3
import uuid
import re

app = Flask(__name__)
app.secret_key = "jarvis_secret_key_2024"

# -------- DATABASE --------

def get_db():
    conn = sqlite3.connect("chat_memory.db", check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chat_sessions (
        chat_id TEXT PRIMARY KEY,
        title TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT,
        role TEXT,
        message TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reminder_date TEXT,
        reminder_text TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS uploaded_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT,
        filename TEXT,
        uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

init_db()

def db_add_reminder(date_str, text):
    conn = get_db()
    conn.execute("INSERT INTO reminders (reminder_date, reminder_text) VALUES (?, ?)", (date_str, text))
    conn.commit(); conn.close()

def db_load_reminders():
    conn = get_db()
    rows = conn.execute("SELECT id, reminder_date, reminder_text FROM reminders ORDER BY reminder_date ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def db_delete_reminder(rem_id):
    conn = get_db()
    conn.execute("DELETE FROM reminders WHERE id = ?", (rem_id,))
    conn.commit(); conn.close()

def db_clear_reminders():
    conn = get_db()
    conn.execute("DELETE FROM reminders")
    conn.commit(); conn.close()

def save_chat(chat_id, role, message):
    conn = get_db()
    conn.execute("INSERT INTO chats (chat_id, role, message) VALUES (?, ?, ?)", (chat_id, role, message))
    conn.commit(); conn.close()

def create_chat_session(chat_id, title):
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO chat_sessions (chat_id, title) VALUES (?, ?)", (chat_id, title))
    conn.commit(); conn.close()

def load_chat_sessions():
    conn = get_db()
    rows = conn.execute("SELECT chat_id, title, created_at FROM chat_sessions ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def load_chat_messages(chat_id):
    conn = get_db()
    rows = conn.execute("SELECT role, message FROM chats WHERE chat_id = ? ORDER BY id ASC", (chat_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def db_save_uploaded_file(chat_id, filename):
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO uploaded_files (chat_id, filename) VALUES (?, ?)", (chat_id, filename))
    conn.commit()
    conn.close()

def db_get_uploaded_files(chat_id):
    conn = get_db()
    rows = conn.execute("SELECT filename, uploaded_at FROM uploaded_files WHERE chat_id = ? ORDER BY uploaded_at DESC", (chat_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_chat(chat_id):
    conn = get_db()
    conn.execute("DELETE FROM chat_sessions WHERE chat_id = ?", (chat_id,))
    conn.commit(); conn.close()

def rename_chat(chat_id, new_title):
    conn = get_db()
    conn.execute("UPDATE chat_sessions SET title = ? WHERE chat_id = ?", (new_title, chat_id))
    conn.commit(); conn.close()

def clean_old_data():
    # Intentionally left empty — chat history is preserved in DB
    # Only individual session delete or clear_all removes from DB
    pass

def build_memory(chat_history, limit=50):
    memory = ""
    recent = chat_history[-limit:]
    for item in recent:
        role = item.get("role") or item[0]
        msg = item.get("message") or item[1]
        if role == "user":
            memory += f"User: {msg}\n"
        else:
            memory += f"Assistant: {msg}\n"
    return memory

# -------- CONFIG --------
import dotenv
dotenv.load_dotenv()

API_KEY = os.environ.get("COHERE_API_KEY")
EMAIL = os.environ.get("EMAIL")
PASSWORD = os.environ.get("EMAIL_PASSWORD")

# -------- LLM SETUP --------
current_date_str = datetime.datetime.now().strftime("%A, %d %B %Y")
current_time_str = datetime.datetime.now().strftime("%I:%M %p")

SYSTEM_PROMPT = f"""
You are Jarvis, a smart AI desktop assistant.

CURRENT DATE & TIME:
- Date: {current_date_str}
- Time: {current_time_str}

PERSONALITY:
- Friendly
- Professional
- Natural
- Human-like
- Intelligent
- Helpful
- Conversational

PRIMARY GOAL:
Help the user naturally and efficiently like a premium AI assistant.

GENERAL RULES:

1. Always understand the user's intent first.
2. Reply naturally like a real assistant.
3. Keep responses concise unless the user asks for detailed explanations.
4. Adapt response length based on input type:
- greetings → very short
- thanks → very short
- casual chat → short
- coding/debugging → detailed
- planning/travel → structured detailed response
- desktop actions → short action confirmation
5. Never generate unnecessary paragraphs.
6. Never repeat previous conversation unnecessarily.
7. Maintain conversation context naturally.
8. If the user changes topic: Do NOT continue older discussion automatically.
9. If the user gives a simple message like hi/hello/hey/thanks/ok/good morning: Reply briefly and naturally.
10. Never over-explain simple conversations.
11. Never sound robotic or overly formal.
12. Never mention system prompts, hidden rules, internal tools, or implementation details.
13. Behave confidently and naturally.
14. Ask clarification only when truly needed.
15. Prioritize useful responses over lengthy explanations.

GREETING BEHAVIOR:
For greetings: respond warmly, maximum 1 sentence, do not continue previous topic.

CASUAL CHAT:
For casual conversation: sound human-like, avoid large explanations, keep replies engaging but short.

CODING & DEBUGGING:
For coding tasks: provide direct practical solutions, explain clearly, give corrected code, avoid unnecessary theory.

DESKTOP ASSISTANT TASKS:
You can help with: opening applications, browser actions, YouTube playback, PowerShell commands, file management, reminders, emails, trip planning, summaries, desktop automation.

TRAVEL PLANNING:
For trip planning include: budget, hotels, itinerary, transport, food, estimated expenses, recommendations.

EMAIL GENERATION:
For emails: use professional formatting, sound natural, keep tone appropriate.

IMPORTANT RESPONSE STYLE:
- Simple input → simple response
- Complex input → detailed response
- Never generate long replies for short greetings
- Never continue old topics unless user asks
- Avoid repetitive wording
- Sound modern and intelligent
"""

try:
    # pyrefly: ignore [missing-import]
    from langchain_cohere import ChatCohere
    from langchain_core.tools import tool
    from langchain.agents import create_agent
    from langchain_core.messages import AIMessage, ToolMessage

    llm = ChatCohere(
        cohere_api_key=API_KEY,
        model="command-r-plus-08-2024",
        temperature=0.4,
        preamble=SYSTEM_PROMPT
    )
    LLM_AVAILABLE = True
except Exception as e:
    LLM_AVAILABLE = False
    print(f"LLM not available: {e}")

# -------- HELPER FUNCTIONS --------

def clean_app_name(name: str) -> str:
    name_clean = name.lower().strip()
    # Remove prefix command words
    name_clean = re.sub(r'^(open|launch|start|run|close|terminate|stop|exit|kill)\s+', '', name_clean).strip()
    # Remove common suffix noise like "from my pc", "on my computer", etc.
    name_clean = re.sub(r'\s+(from|on)\s+(my\s+)?(pc|computer)$', '', name_clean).strip()
    # Remove general app/application suffixes
    name_clean = re.sub(r'\s+(app|application|exe|program|browser)$', '', name_clean).strip()
    return name_clean

def extract_name_from_email(email):
    name_part = email.split("@")[0]
    name_only = ''.join([c for c in name_part if not c.isdigit()])
    words = re.findall('[A-Z]?[a-z]+', name_only)
    return " ".join([w.capitalize() for w in words])

def parse_send_email_command(text):
    lower = text.lower()
    if "email" not in lower:
        return None
    email_match = re.search(r"([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)", text)
    if not email_match:
        return None
    email_addr = email_match.group(1).strip()
    attachment_path = None
    topic_text = text
    file_matches = re.findall(r"([a-zA-Z0-9_-]+\.[a-zA-Z0-9]+)", text)
    for fm in file_matches:
        if fm not in email_addr:
            attachment_path = fm.strip()
            topic_text = text.replace(attachment_path, "")
            break
    if not attachment_path:
        attach_match = re.search(r"(?:attach|with file|send file)\s+([^\s]+)", text, flags=re.IGNORECASE)
        if attach_match:
            attachment_path = attach_match.group(1).strip()
            topic_text = text.replace(attach_match.group(0), "")
    topic = "General"
    if "about" in topic_text.lower():
        parts = re.split(r"about", topic_text, flags=re.IGNORECASE, maxsplit=1)
        if len(parts) == 2:
            topic = parts[1].strip()
    return email_addr, topic, attachment_path

def send_email_fn(text):
    parsed = parse_send_email_command(text)
    if not parsed:
        return "Use format: send email to email@gmail.com about topic [attach file.txt]"
    email_addr, topic, attachment_path = parsed
    name = extract_name_from_email(EMAIL)
    if attachment_path and topic == "General":
        content = f"Please find the attached file: {attachment_path}\n\nYours sincerely,\n{name}"
    else:
        ai = llm.invoke(f"Write a professional email about {topic}.\n\nEnd the email with:\nYours sincerely,\n{name}")
        content = ai.content if hasattr(ai, "content") else str(ai)
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase
    from email import encoders
    msg = MIMEMultipart()
    msg['Subject'] = topic
    msg['From'] = EMAIL
    msg['To'] = email_addr
    msg.attach(MIMEText(content, 'plain'))
    if attachment_path:
        if os.path.exists(attachment_path):
            try:
                with open(attachment_path, "rb") as attachment:
                    part = MIMEBase("application", "octet-stream")
                    part.set_payload(attachment.read())
                encoders.encode_base64(part)
                part.add_header("Content-Disposition", f"attachment; filename={os.path.basename(attachment_path)}")
                msg.attach(part)
            except Exception as e:
                return f"Could not read attachment {attachment_path}: {str(e)}"
        else:
            return f"Attachment file not found: {attachment_path}"
    try:
        server = smtplib.SMTP_SSL('smtp.gmail.com', 465)
        server.login(EMAIL, PASSWORD)
        server.send_message(msg)
        server.quit()
        return f"Email sent to {email_addr}"
    except Exception as e:
        return f"Email send failed: {str(e)}"

def is_notepad_summary_command(text):
    lower = text.lower()
    return "summary" in lower and "notepad" in lower

def extract_summary_topic(text, last_assistant=""):
    cleaned = re.sub(
        r'\b(create|generate|make|write|summarize|summary|in notepad|notepad|open notepad|save in notepad|save to notepad)\b',
        "", text, flags=re.IGNORECASE).strip(" .")
    if cleaned:
        return cleaned
    if last_assistant:
        return f"Create a concise summary of the following response:\n{last_assistant}"
    return "Create a concise summary of the current conversation."

def notepad_summary_fn(topic):
    response = llm.invoke(f"Generate a concise and clear summary about {topic}. Keep it informative and easy to read.")
    content = response.content if hasattr(response, "content") else str(response)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    clean_topic = "".join([c for c in topic if c.isalnum() or c == ' ']).rstrip().replace(' ', '_')
    if not clean_topic:
        clean_topic = "topic"
    filename = f"summary_{clean_topic}_{timestamp}.txt"
    with open(filename, "w", encoding="utf-8") as f:
        f.write(content)
    try:
        subprocess.Popen(["notepad.exe", filename])
    except Exception:
        pass
    return f"Summary opened in Notepad as {filename}"

def is_trip_plan_command(text):
    lower = text.lower()
    return "trip" in lower and ("plan" in lower or "budget" in lower or "itinerary" in lower or "travel" in lower or "goa" in lower)

def is_trip_budget_question(text):
    lower = text.lower().strip()
    if "trip budget" in lower:
        return lower.endswith("?") or lower.startswith("what") or lower.startswith("how") or "tell me" in lower
    return (("what was" in lower or "what is" in lower or "how much" in lower or "tell me" in lower) and "budget" in lower)

def is_trip_budget_statement(text):
    lower = text.lower()
    return "my trip budget" in lower and ("is" in lower or "for" in lower or re.search(r"\d", text) is not None)

def parse_budget_amount(text):
    patterns = [r'₹\s*([\d,]+)', r'budget\s*(?:is|:|=)?\s*₹?\s*([\d,]+)', r'([\d,]+)\s*(?:inr|rs|rupees|rupee)']
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            amount = re.sub(r"[^\d]", "", match.group(1))
            if amount:
                return amount
    return None

def extract_location_terms(text):
    words = re.findall(r"\b[a-zA-Z]+\b", text.lower())
    stopwords = {"what","was","my","trip","budget","is","the","for","in","on","about","how","much","tell","me","i","did","you","of","to","your","and","with","from","at","by","a","an","it","that","this","now"}
    return [word for word in words if word not in stopwords and len(word) > 2]

def parse_budget_declarations(text):
    normalized = re.sub(r"\s+", " ", text)
    declarations = []
    for match in re.finditer(r"\b([A-Za-z][A-Za-z ]{0,40}?)\s+for\s+₹?\s*([\d,]+)\b", normalized, flags=re.IGNORECASE):
        place = match.group(1).strip(" .,-").lower()
        amount = re.sub(r"[^\d]", "", match.group(2))
        if place and amount:
            declarations.append({"place": place, "amount": amount})
    for match in re.finditer(r"budget\s*(?:is|:|=)?\s*₹?\s*([\d,]+)\s*(?:for|in)\s+([A-Za-z][A-Za-z ]{0,40}?)\b", normalized, flags=re.IGNORECASE):
        amount = re.sub(r"[^\d]", "", match.group(1))
        place = match.group(2).strip(" .,-").lower()
        if place and amount:
            declarations.append({"place": place, "amount": amount})
    for match in re.finditer(r"\b([A-Za-z][A-Za-z ]{0,40}?)\s+budget\s*(?:is|:|=)?\s*₹?\s*([\d,]+)\b", normalized, flags=re.IGNORECASE):
        place = match.group(1).strip(" .,-").lower()
        amount = re.sub(r"[^\d]", "", match.group(2))
        if place and amount:
            declarations.append({"place": place, "amount": amount})
    return declarations

def match_budget_declaration(declarations, query_terms):
    if not declarations:
        return None
    if not query_terms:
        return declarations[0]["amount"]
    best_amount = None
    best_score = 0
    for entry in declarations:
        place_text = entry["place"]
        score = sum(1 for term in query_terms if term in place_text)
        if score > best_score:
            best_score = score
            best_amount = entry["amount"]
    return best_amount if best_score > 0 else None

def extract_budget_from_message(msg):
    declarations = parse_budget_declarations(msg)
    if declarations:
        return declarations[0]["amount"]
    lower = msg.lower()
    lines = msg.splitlines()
    for line in lines:
        lower_line = line.lower()
        if "total budget" in lower_line or lower_line.strip().startswith("total:") or "total cost" in lower_line:
            amount = parse_budget_amount(line)
            if amount:
                return amount
    for line in lines:
        if "budget" in line.lower():
            amount = parse_budget_amount(line)
            if amount:
                return amount
    amounts = re.findall(r'₹\s*([\d,]+)|([\d,]+)\s*(?:inr|rs|rupees|rupee|₹)', msg, flags=re.IGNORECASE)
    cleaned = []
    for a, b in amounts:
        candidate = a or b
        if candidate:
            num = re.sub(r"[^\d]", "", candidate)
            if num:
                cleaned.append(int(num))
    if cleaned:
        return str(max(cleaned))
    return None

def extract_trip_budget(chat_history, user_input=""):
    query_terms = extract_location_terms(user_input)
    best_amount = None
    best_score = 0
    for item in reversed(chat_history):
        role = item.get("role") or item[0]
        msg = item.get("message") or item[1]
        if role != "assistant" or "budget" not in msg.lower():
            continue
        score = sum(1 for term in query_terms if term in msg.lower())
        if score > 0:
            declarations = parse_budget_declarations(msg)
            if declarations:
                amount = match_budget_declaration(declarations, query_terms)
            else:
                amount = extract_budget_from_message(msg)
            if amount and score > best_score:
                best_amount = amount
                best_score = score
    if best_amount:
        return best_amount
    for item in reversed(chat_history):
        role = item.get("role") or item[0]
        msg = item.get("message") or item[1]
        if role != "user" or "budget" not in msg.lower():
            continue
        declarations = parse_budget_declarations(msg)
        if declarations:
            matched = match_budget_declaration(declarations, query_terms)
            if matched:
                return matched
        if not query_terms or any(term in msg.lower() for term in query_terms):
            amount = parse_budget_amount(msg)
            if amount:
                return amount
    return None

def plan_trip_fn(user_input):
    try:
        prompt = f"""
        You are an expert AI travel planner.
        User Request: {user_input}
        Create a detailed travel plan with this EXACT FORMAT:
        📍 DESTINATION: [Place Name]
        💰 TOTAL BUDGET: [Amount in INR]
        📅 DAYS: [Number of days]
        ✈️ FLIGHTS:
        - [Airline] from [City] to [Destination]
        - Approximate cost: ₹[Price]
        🏨 ACCOMMODATION:
        - [Hotel 1]: ₹[Price/night]
        - [Hotel 2]: ₹[Price/night]
        - [Budget Option]: ₹[Price/night]
        🎯 DAILY ITINERARY:
        Day 1: [Activity 1] → [Activity 2]
        Day 2: [Activity 3] → [Activity 4]
        🍽️ FOOD & ACTIVITIES:
        - [Activity 1]: ₹[Cost]
        - [Food]: ₹[Cost/day]
        🚗 LOCAL TRANSPORT: ₹[Cost/day]
        💵 BUDGET BREAKDOWN:
        - Flights: ₹[Amount]
        - Hotel: ₹[Amount]
        - Food: ₹[Amount]
        - Activities: ₹[Amount]
        - Transport: ₹[Amount]
        - TOTAL: ₹[Amount]
        IMPORTANT: Use REAL prices, include all costs, return ONLY text response.
        """
        response = llm.invoke(prompt)
        return response.content if hasattr(response, "content") else str(response)
    except Exception as e:
        return f"Trip Planning Error: {str(e)}"

def get_existing_files():
    try:
        items = os.listdir(".")
        exclude = {".git", "venv", "__pycache__", ".benchmarks", "chat_memory.db", ".gemini", "templates", "static"}
        return [item for item in items if item not in exclude and not item.startswith(".")]
    except Exception:
        return []

def find_closest_path_in_system(target_name):
    if not target_name:
        return None
    try:
        import difflib
        if os.path.exists(target_name):
            return os.path.abspath(target_name)
        target_name_normalized = target_name.replace(" dot ", ".").replace("dot", ".").replace(" ", "_").strip()
        if os.path.isabs(target_name_normalized) or ":" in target_name_normalized:
            drive_part, rest = os.path.splitdrive(target_name_normalized)
            if drive_part:
                parent_dir = drive_part + "\\"
                if rest:
                    parts = [p for p in rest.split(os.sep) if p]
                    potential_path = os.path.join(parent_dir, *parts)
                    if os.path.exists(potential_path):
                        return potential_path
                    if len(parts) > 0:
                        reconstructed_parent = os.path.join(parent_dir, *parts[:-1])
                        if os.path.exists(reconstructed_parent):
                            items = os.listdir(reconstructed_parent)
                            file_to_match = parts[-1]
                            matches = difflib.get_close_matches(file_to_match, items, n=1, cutoff=0.5)
                            if matches:
                                return os.path.join(reconstructed_parent, matches[0])
        candidates = []
        home = os.path.expanduser("~")
        search_dirs = [".", os.path.join(home, "Desktop"), os.path.join(home, "Documents"), os.path.join(home, "Downloads"), "C:\\", "D:\\"]
        for base in search_dirs:
            if not os.path.exists(base):
                continue
            try:
                for item in os.listdir(base):
                    exclude = {".git","venv","__pycache__",".benchmarks","chat_memory.db",".gemini","System Volume Information","$RECYCLE.BIN"}
                    if item not in exclude and not item.startswith("."):
                        candidates.append((os.path.join(base, item), item))
            except Exception:
                continue
        for full_path, basename in candidates:
            if target_name.lower() == basename.lower():
                return full_path
        normalized_target = target_name.replace(" dot ", ".").replace("dot", ".").replace(" ", "_").strip()
        for full_path, basename in candidates:
            if normalized_target.lower() == basename.lower():
                return full_path
        target_words = [w.lower() for w in target_name.replace(".", " ").replace("_", " ").replace("-", " ").split() if len(w) > 2]
        if target_words:
            best_match = None
            best_score = 0
            for full_path, basename in candidates:
                score = sum(1 for w in target_words if w in basename.lower())
                if score > best_score:
                    best_score = score
                    best_match = full_path
            if best_score >= max(1, len(target_words) // 2):
                return best_match
        basenames = [item[1] for item in candidates]
        matches = difflib.get_close_matches(target_name, basenames, n=1, cutoff=0.4)
        if matches:
            for full_path, basename in candidates:
                if basename == matches[0]:
                    return full_path
        return None
    except Exception:
        return None

def resolve_new_path(name):
    name = name.strip()
    home = os.path.expanduser("~")
    folders = {
        "desktop": os.path.join(home, "Desktop"),
        "documents": os.path.join(home, "Documents"),
        "downloads": os.path.join(home, "Downloads"),
        "c drive": "C:\\", "d drive": "D:\\",
        "c:\\": "C:\\", "d:\\": "D:\\",
        "c": "C:\\", "d": "D:\\",
        "this folder": os.getcwd(), "current folder": os.getcwd(),
        "current directory": os.getcwd(), "here": os.getcwd(), "workspace": os.getcwd(),
    }
    sorted_keys = sorted(folders.keys(), key=len, reverse=True)
    lower_name = name.lower()
    target_folder = None
    for key in sorted_keys:
        folder_path = folders[key]
        pattern = rf"\b(in|on|inside|to|under|within|into)\s+(my\s+)?{re.escape(key)}(\s+(folder|drive|directory|partition|vol|volume))?\b"
        if re.search(pattern, lower_name):
            target_folder = folder_path
            name = re.sub(pattern, "", name, flags=re.IGNORECASE).strip()
            break
    subfolder_pattern = rf"\b(in|on|inside|to|under|within|into)\s+([a-zA-Z0-9_-]+)(\s+(folder|directory))?\b"
    while True:
        match = re.search(subfolder_pattern, name, flags=re.IGNORECASE)
        if match:
            sub_name = match.group(2)
            if "." not in sub_name:
                if target_folder:
                    target_folder = os.path.join(target_folder, sub_name)
                else:
                    target_folder = sub_name
                name = re.sub(subfolder_pattern, "", name, count=1, flags=re.IGNORECASE).strip()
                continue
        break
    name_clean = name.replace(" dot ", ".").replace("dot", ".").strip()
    name_clean = re.sub(r'^[_\s\W]+|[_\s\W]+$', '', name_clean)
    name_clean = name_clean.replace(" ", "_")
    if name_clean and "." not in name_clean:
        name_clean += ".txt"
    if not name_clean:
        name_clean = "new_file.txt"
    if target_folder:
        return os.path.join(target_folder, name_clean)
    if os.path.isabs(name_clean) or ":" in name_clean:
        return name_clean
    return name_clean

def get_unique_topic_filename(topic_text):
    cleaned = re.sub(r'\b(create|generate|make|write|code|for|python|in vscode|in vs code|vs code|vscode)\b', "", topic_text, flags=re.IGNORECASE).strip(" ._-")
    clean_topic = "".join([c if (c.isalnum() or c == '_') else '_' for c in cleaned])
    clean_topic = re.sub(r'_+', '_', clean_topic).strip('_').lower()
    if not clean_topic:
        clean_topic = "generated_code"
    filename = f"{clean_topic}.py"
    counter = 1
    while os.path.exists(filename):
        filename = f"{clean_topic}_{counter}.py"
        counter += 1
    return filename

def locate_file_in_system(filename):
    filename = filename.strip()
    if os.path.exists(filename):
        return os.path.abspath(filename)
    
    # 1. Search current directory recursively (excluding virtual environments and git folders)
    for root, dirs, files in os.walk("."):
        dirs[:] = [d for d in dirs if d not in {".git", "venv", "__pycache__", "node_modules"}]
        for f in files:
            if f.lower() == filename.lower():
                return os.path.abspath(os.path.join(root, f))
                
    # 2. Use find_closest_path_in_system as fallback
    match = find_closest_path_in_system(filename)
    if match and os.path.exists(match):
        return os.path.abspath(match)
        
    # 3. Search Desktop/Documents/Downloads recursively up to depth 3
    home = os.path.expanduser("~")
    for base in [os.path.join(home, "Desktop"), os.path.join(home, "Documents"), os.path.join(home, "Downloads")]:
        if os.path.exists(base):
            for root, dirs, files in os.walk(base):
                depth = root[len(base):].count(os.sep)
                if depth > 3:
                    dirs[:] = []
                    continue
                dirs[:] = [d for d in dirs if d not in {".git", "venv", "__pycache__"}]
                for f in files:
                    if f.lower() == filename.lower():
                        return os.path.abspath(os.path.join(root, f))
    return None

def run_and_debug_file_fn(filename: str):
    filename_clean = filename.lower().strip()
    filename_clean = re.sub(r'^(run|execute|start|launch|debug|solve)\s+', '', filename_clean).strip()
    if not filename_clean.endswith(".py"):
        filename_clean += ".py"
        
    filepath = locate_file_in_system(filename_clean)
    if not filepath:
        return f"I am sorry, but I couldn't find any file named '{filename_clean}' on this PC."
        
    # Open in VS Code
    os.system(f'code "{filepath}"')
    
    # Self-healing execution loop
    python_exe = "venv\\Scripts\\python.exe" if os.path.exists("venv\\Scripts\\python.exe") else "python"
    attempts = 3
    history = []
    
    for attempt in range(1, attempts + 1):
        try:
            result = subprocess.run([python_exe, filepath], capture_output=True, text=True, timeout=25)
            
            if result.returncode == 0:
                output_msg = result.stdout.strip()
                return f"✅ Successfully ran {filename_clean} with no errors on attempt {attempt}!\n\n🖥 Output:\n{output_msg}"
            
            # We have an error
            error_msg = result.stderr.strip() if result.stderr.strip() else result.stdout.strip()
            history.append(f"Attempt {attempt} Error:\n{error_msg}")
            
            if attempt == attempts:
                break
                
            with open(filepath, "r", encoding="utf-8") as f:
                code_content = f.read()
                
            prompt = f"""You are a senior developer. The following python script failed with an error.
Fix the code to resolve the error and make it run successfully.

File: {filepath}
Current Code:
```python
{code_content}
```

Error:
{error_msg}

Return ONLY the corrected, clean python code. Do not include markdown formatting, markdown backticks, or explanation.
"""
            ai_resp = llm.invoke(prompt)
            fixed_code = ai_resp.content if hasattr(ai_resp, "content") else str(ai_resp)
            if "```" in fixed_code:
                fixed_code = fixed_code.replace("```python", "").replace("```", "").strip()
            
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(fixed_code)
                
        except subprocess.TimeoutExpired:
            error_msg = "⏰ execution timeout (possible infinite loop)"
            history.append(f"Attempt {attempt} Error: {error_msg}")
            if attempt == attempts:
                break
            with open(filepath, "r", encoding="utf-8") as f:
                code_content = f.read()
            prompt = f"""The following python script has an infinite loop or runs forever.
Modify the code to run correctly, output results, and exit without infinite loops.

File: {filepath}
Current Code:
```python
{code_content}
```

Return ONLY the corrected, clean python code. Do not include markdown formatting, markdown backticks, or explanation.
"""
            ai_resp = llm.invoke(prompt)
            fixed_code = ai_resp.content if hasattr(ai_resp, "content") else str(ai_resp)
            if "```" in fixed_code:
                fixed_code = fixed_code.replace("```python", "").replace("```", "").strip()
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(fixed_code)
        except Exception as e:
            return f"❌ Unexpected error while debugging {filename_clean}: {str(e)}"
            
    errors_summary = "\n\n".join(history)
    return f"❌ Tried to automatically debug and run {filename_clean} {attempts} times, but errors persist.\n\n⚠️ Error History:\n{errors_summary}\n\nThe latest code version is saved. You can edit it manually in VS Code."

def generate_code_in_vscode_fn(topic: str):
    response = llm.invoke(f"Write python code for: {topic}. Provide ONLY the code without any markdown backticks or explanation.")
    code_content = response.content if hasattr(response, 'content') else str(response)
    if "```" in code_content:
        code_content = code_content.replace("```python", "").replace("```", "").strip()
    filename = get_unique_topic_filename(topic)
    with open(filename, "w", encoding="utf-8") as f:
        f.write(code_content)
    try:
        subprocess.Popen(f"code {filename}", shell=True)
        return f"Code generated and opened in VS Code as {filename}"
    except Exception as e:
        return f"Created {filename} but couldn't open VS Code: {e}"



# -------- TOOLS --------

try:
    from langchain.tools import tool

    @tool
    def run_powershell(command: str):
        """Runs PowerShell command safely"""
        try:
            background_commands = ["streamlit", "python", "powershell", "cmd"]
            if any(command.lower().startswith(cmd) for cmd in background_commands):
                subprocess.Popen(["powershell", "-Command", command], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
                return f"✅ Started in background:\n{command}"
            result = subprocess.run(["powershell", "-Command", command], capture_output=True, text=True, timeout=20)
            output = result.stdout.strip()
            error = result.stderr.strip()
            if error:
                return f"❌ Error:\n{error}"
            if not output:
                return "✅ Command executed successfully"
            return f"🖥 Output:\n{output}"
        except subprocess.TimeoutExpired:
            return "⏰ Command timeout"
        except Exception as e:
            return f"❌ {str(e)}"

    @tool
    def open_path(name: str):
        """Opens a file or folder by its path"""
        name = name.strip()
        matched = find_closest_path_in_system(name)
        if matched and os.path.exists(matched):
            os.startfile(matched)
            return f"Opened {matched}"
        home = os.path.expanduser("~")
        search_dirs = [home, "C:\\", "D:\\", os.path.join(home, "Desktop"), os.path.join(home, "Documents"), os.path.join(home, "Downloads")]
        for base in search_dirs:
            if not os.path.exists(base):
                continue
            for root, dirs, files in os.walk(base):
                if name.lower() in [d.lower() for d in dirs]:
                    path = os.path.join(root, name)
                    os.startfile(path)
                    return f"Opened folder {path}"
        return "❌ Folder or file not found"

    @tool
    def notepad_summary(topic: str):
        """Opens Notepad with a generated summary for the given topic."""
        return notepad_summary_fn(topic)

    @tool
    def open_application(name: str):
        """Opens any application based on user input."""
        name_clean = clean_app_name(name)
        app_map = {
            "chrome": "chrome", "notepad": "notepad", "word": "winword",
            "vscode": "code", "vs code": "code", "calculator": "calc",
            "powershell": "powershell", "idle": "idle.pyw", "edge": "msedge",
            "vlc": "vlc", "excel": "excel", "powerpoint": "powerpnt",
            "command prompt": "cmd", "cmd": "cmd"
        }
        exe_name = app_map.get(name_clean, name_clean)
        os.system(f"start {exe_name}")
        return f"Attempted to open {name_clean}"

    @tool
    def get_time():
        """Returns the current time"""
        return datetime.datetime.now().strftime("%I:%M %p")

    @tool
    def get_date(query: str = "today"):
        """Returns the date based on the query."""
        now = datetime.datetime.now()
        lower_query = query.lower()
        if "tomorrow" in lower_query:
            target_date = now + datetime.timedelta(days=1)
        elif "yesterday" in lower_query:
            target_date = now - datetime.timedelta(days=1)
        elif "day after tomorrow" in lower_query:
            target_date = now + datetime.timedelta(days=2)
        elif "day before yesterday" in lower_query:
            target_date = now - datetime.timedelta(days=2)
        else:
            target_date = now
        return target_date.strftime("%A, %d %B %Y")

    @tool
    def create_file(name: str):
        """Creates a new file with the given name"""
        resolved = resolve_new_path(name)
        parent = os.path.dirname(resolved)
        if parent and not os.path.exists(parent):
            try:
                os.makedirs(parent)
            except Exception:
                pass
        open(resolved, "w").close()
        return f"{resolved} created"

    @tool
    def delete_file(name: str):
        """Deletes a file with the given name"""
        name = name.strip()
        matched = find_closest_path_in_system(name)
        if matched and os.path.exists(matched):
            os.remove(matched)
            return f"{matched} deleted"
        return f"File '{name}' not found."

    @tool
    def rename_file(text: str):
        """Renames a file from the old name to the new name"""
        try:
            if " to " not in text:
                return "Format: old.txt to new.txt"
            old, new = text.split(" to ")
            old = old.strip(); new = new.strip()
            old_matched = find_closest_path_in_system(old)
            if not old_matched:
                return f"File '{old}' not found."
            new_resolved = resolve_new_path(new)
            if not os.path.isabs(new_resolved) and ":" not in new_resolved:
                parent_dir = os.path.dirname(old_matched)
                new_resolved = os.path.join(parent_dir, new_resolved)
            parent = os.path.dirname(new_resolved)
            if parent and not os.path.exists(parent):
                os.makedirs(parent)
            os.rename(old_matched, new_resolved)
            return f"File '{old_matched}' renamed to '{new_resolved}'"
        except Exception as e:
            return f"Error: {str(e)}"

    @tool
    def send_email(text: str):
        """Sends an email about a given topic"""
        return send_email_fn(text)

    @tool
    def open_calendar():
        """Opens Google Calendar"""
        webbrowser.open("https://calendar.google.com/")
        return "Calendar opened"

    @tool
    def add_reminder(text: str):
        """Adds a reminder with optional date parsing."""
        now = datetime.date.today()
        target_date = now
        lower_text = text.lower()
        if "tomorrow" in lower_text:
            target_date = now + datetime.timedelta(days=1)
        elif "day after tomorrow" in lower_text:
            target_date = now + datetime.timedelta(days=2)
        elif "next week" in lower_text:
            target_date = now + datetime.timedelta(days=7)
        elif "yesterday" in lower_text:
            target_date = now - datetime.timedelta(days=1)
        clean_text = text
        clean_text = re.sub(r'^(remind me to|remind me|reminder to|reminder)\s+', '', clean_text, flags=re.IGNORECASE).strip()
        clean_text = re.sub(r'\s+on\s+(today|tomorrow|yesterday|next week|day after tomorrow)', '', clean_text, flags=re.IGNORECASE).strip()
        clean_text = re.sub(r'\s+(today|tomorrow|yesterday|next week|day after tomorrow)', '', clean_text, flags=re.IGNORECASE).strip()
        if clean_text:
            clean_text = clean_text[0].upper() + clean_text[1:]
        else:
            clean_text = "Task"
        date_str = target_date.strftime("%Y-%m-%d")
        db_add_reminder(date_str, clean_text)
        return f"Reminder added for {target_date.strftime('%A, %d %B %Y')}: {clean_text}"

    @tool
    def plan_trip(user_input: str):
        """Tool wrapper for trip planning"""
        return plan_trip_fn(user_input)

    @tool
    def play_youtube(video: str):
        """Play first YouTube video automatically"""
        import requests
        import urllib.parse
        try:
            query = urllib.parse.quote(video)
            headers = {"User-Agent": "Mozilla/5.0"}
            search_url = f"https://www.youtube.com/results?search_query={query}"
            html = requests.get(search_url, headers=headers, timeout=10).text
            video_ids = re.findall(r'"videoId":"(.*?)"', html)
            if not video_ids:
                return "❌ No video found"
            first_video_id = video_ids[0]
            video_url = f"https://www.youtube.com/watch?v={first_video_id}&autoplay=1"
            import time as t
            import pyautogui
            subprocess.Popen(f'start "" "{video_url}"', shell=True)
            t.sleep(3.5)
            pyautogui.press("k")
            pyautogui.press("space")
            return f"▶ Playing {video}"
        except Exception as e:
            return f"❌ {str(e)}"

    @tool
    def shutdown_pc():
        """Shuts down the PC"""
        os.system("shutdown /s /t 1")
        return "Shutting down"

    @tool
    def restart_pc():
        """Restarts the PC"""
        os.system("shutdown /r /t 1")
        return "Restarting"

    @tool
    def close_application(name: str):
        """Closes an open application"""
        name_clean = clean_app_name(name)
        app_map = {
            "chrome": ["chrome.exe"], "notepad": ["notepad.exe"], "word": ["winword.exe"],
            "vscode": ["code.exe"], "vs code": ["code.exe"], "calculator": ["CalculatorApp.exe", "Calculator.exe"],
            "powershell": ["powershell.exe"], "idle": ["pythonw.exe"], "edge": ["msedge.exe"],
            "vlc": ["vlc.exe"], "command prompt": ["cmd.exe"], "cmd": ["cmd.exe"]
        }
        exe_names = app_map.get(name_clean, [f"{name_clean}.exe"])
        for exe in exe_names:
            os.system(f"taskkill /F /IM {exe}")
        return f"Closed {name_clean}"

    @tool
    def stop_youtube():
        """Stops YouTube by closing the YouTube tab"""
        try:
            # pyrefly: ignore [missing-import]
            import pygetwindow as gw
            import pyautogui
            import time as t
            windows = gw.getWindowsWithTitle("YouTube")
            if windows:
                for w in windows:
                    try:
                        w.activate()
                        t.sleep(0.5)
                        pyautogui.hotkey('ctrl', 'w')
                    except Exception:
                        pass
                return "Closed YouTube tab(s)"
            browser_windows = []
            for title in ["Edge", "Chrome", "Brave", "Firefox"]:
                browser_windows.extend(gw.getWindowsWithTitle(title))
            closed = False
            for w in browser_windows:
                try:
                    w.activate()
                    t.sleep(0.5)
                    for _ in range(15):
                        active_window = gw.getActiveWindow()
                        if active_window and "YouTube" in active_window.title:
                            pyautogui.hotkey('ctrl', 'w')
                            closed = True
                            break
                        pyautogui.hotkey('ctrl', 'tab')
                        t.sleep(0.2)
                    if closed:
                        break
                except Exception:
                    continue
            if closed:
                return "Closed YouTube tab"
            return "No YouTube window found"
        except Exception as e:
            return f"Could not close YouTube: {str(e)}"

    @tool
    def generate_code_in_vscode(topic: str):
        """Generates code and opens it in VS Code."""
        return generate_code_in_vscode_fn(topic)

    @tool
    def open_vscode():
        """Opens Visual Studio Code."""
        os.system("start code")
        return "Opened VS Code"

    @tool
    def close_calendar():
        """Closes Google Calendar tab"""
        try:
            # pyrefly: ignore [missing-import]
            import pygetwindow as gw
            import pyautogui
            import time as t
            windows = []
            for title in ["Google Calendar", "Calendar -", "- Calendar"]:
                windows.extend(gw.getWindowsWithTitle(title))
            if windows:
                for w in windows:
                    try:
                        w.activate()
                        t.sleep(0.5)
                        pyautogui.hotkey('ctrl', 'w')
                    except Exception:
                        pass
                return "Closed Calendar tab(s)"
            return "No Calendar window found"
        except Exception as e:
            return f"Could not close Calendar: {str(e)}"

    @tool
    def run_and_debug_file(filename: str):
        """Finds a python file on the PC, opens it in VS Code, runs it automatically, and self-heals any errors using the AI."""
        return run_and_debug_file_fn(filename)

    tools = [
        open_application, get_time, get_date, create_file, delete_file, rename_file,
        send_email, open_calendar, add_reminder, shutdown_pc, restart_pc,
        close_application, stop_youtube, open_path, notepad_summary, plan_trip,
        play_youtube, run_powershell, generate_code_in_vscode, open_vscode, close_calendar,
        run_and_debug_file
    ]

    agent = create_agent(llm, tools)
    TOOLS_AVAILABLE = True

except Exception as e:
    TOOLS_AVAILABLE = False
    print(f"Tools not available: {e}")

# -------- SPEECH PREPROCESSING & LOCAL EXECUTOR --------

def preprocess_speech_input(text):
    text_lower = text.lower().strip()
    
    # Clean up speech transcription errors for Python file names (e.g., 'dot py' -> '.py')
    text_lower = re.sub(r'\s+dot\s+(py|p\s+y|pie|buy|pay|by)\b', '.py', text_lower)
    
    # Check if empty or too short / junk
    if not text_lower or len(text_lower) < 2:
        return "not_clearly_heard"
        
    # Standard fuzzy corrections for common speech mistakes
    corrections = {
        "yes code": "open vs code",
        "peace code": "open vs code",
        "peacecode": "open vs code",
        "we is code": "open vs code",
        "discourse": "open vs code",
        "open yes code": "open vs code",
        "open peace code": "open vs code",
        "open peacecode": "open vs code",
        "open we is code": "open vs code",
        "open discourse": "open vs code",
        "close yes code": "close vs code",
        "close peace code": "close vs code",
        "close peacecode": "close vs code",
        "close we is code": "close vs code",
        "close discourse": "close vs code",
        "gogle chrom": "chrome",
        "gogle chrome": "chrome",
        "open browser": "open chrome",
        "open internet": "open chrome",
        "rom": "chrome",
        "chrom": "chrome",
        "open rom": "open chrome",
        "open chrom": "open chrome",
        "not pad": "notepad",
        "note pad": "notepad",
        "open not pad": "open notepad",
        "open note pad": "open notepad",
        "close not pad": "close notepad",
        "close note pad": "close notepad",
        "stop you tube": "stop youtube",
        "stop youtub": "stop youtube",
        "close youtube": "stop youtube",
        "close you tube": "stop youtube",
        "close youtub": "stop youtube",
        "what is time": "what time is it",
        "tell me time": "what time is it",
        "what's the time": "what time is it",
        "what is date": "what is the date today",
        "tell me date": "what is the date today",
        "what's the date": "what is the date today",
    }
    
    # Exact matches or replacements
    if text_lower in corrections:
        return corrections[text_lower]
        
    # Check if it starts with misheard prefix or contains them
    for misheard, correct in corrections.items():
        if text_lower.startswith(misheard):
            return text_lower.replace(misheard, correct)
            
    return text

def try_local_command_execution(user_input):
    text = user_input.lower().strip()
    
    # Handle running and self-healing python files
    run_file_match = re.match(r"^(run|execute|debug|solve|start|launch)\s+([a-zA-Z0-9_-]+\.py)$", text)
    if not run_file_match:
        run_file_match = re.match(r"^([a-zA-Z0-9_-]+\.py)$", text)
        
    if run_file_match:
        target_file = run_file_match.group(run_file_match.lastindex).strip()
        return run_and_debug_file_fn(target_file)
        

        
    # Handle notepad summary
    if "summary" in text and "notepad" in text:
        topic = extract_summary_topic(text)
        return notepad_summary_fn(topic)
    if text.startswith("summarize "):
        topic = re.sub(r"^summarize\s+", "", text).strip()
        topic = re.sub(r"\s+(in|to|on)\s+notepad$", "", topic, flags=re.IGNORECASE).strip()
        return notepad_summary_fn(topic)
        
    # Handle VS Code code generation
    if "code" in text and ("vs code" in text or "vscode" in text or "yes code" in text or "peace code" in text) and not any(text.startswith(word) for word in ["close", "terminate", "stop", "exit", "kill", "open", "launch", "start", "run"]):
        topic = text
        topic = re.sub(
            r'\b(generate|write|create|make|python|code|for|in|vscode|vs\s*code|yes\s*code|peace\s*code)\b',
            "", topic, flags=re.IGNORECASE
        ).strip(" ._-")
        if not topic:
            topic = "generated_code"
        return generate_code_in_vscode_fn(topic)
        
    code_gen_match = re.match(r"^(generate|write|create|make)\s+(python\s+)?code\s+for\s+(.*)$", text)
    if code_gen_match:
        topic = code_gen_match.group(3).strip()
        topic = re.sub(r"\s+in\s+vs\s*code$", "", topic, flags=re.IGNORECASE).strip()
        return generate_code_in_vscode_fn(topic)
        
    # Handle time / date
    if any(p in text for p in ["what time is it", "what is the time", "tell me the time", "current time", "what time"]):
        now = datetime.datetime.now().strftime("%I:%M %p")
        return f"The current time is {now}."
        
    if any(p in text for p in ["what date is today", "what is today's date", "what is the date today", "current date", "what's the date", "what is the date", "what is date"]):
        now = datetime.datetime.now().strftime("%A, %d %B %Y")
        return f"Today is {now}."

    # Handle open applications
    open_match = re.match(r"^(open|launch|start|run)\s+(.*)$", text)
    if open_match:
        app_name = clean_app_name(open_match.group(2).strip())
        app_map = {
            "chrome": "chrome", "google chrome": "chrome", "browser": "chrome",
            "notepad": "notepad", "note pad": "notepad",
            "word": "winword", "ms word": "winword", "microsoft word": "winword",
            "vscode": "code", "vs code": "code", "visual studio code": "code", "yes code": "code", "peace code": "code", "discourse": "code",
            "calculator": "calc", "calc": "calc",
            "powershell": "powershell", "idle": "idle.pyw", 
            "edge": "msedge", "microsoft edge": "msedge",
            "vlc": "vlc", "vlc media player": "vlc",
            "excel": "excel", "ms excel": "excel", "microsoft excel": "excel",
            "powerpoint": "powerpnt", "ms powerpoint": "powerpnt", "microsoft powerpoint": "powerpnt",
            "command prompt": "cmd", "cmd": "cmd",
            "calendar": "calendar", "google calendar": "calendar",
            "camera": "microsoft.windows.camera:"
        }
        if app_name in app_map:
            exe_name = app_map[app_name]
            if exe_name == "calendar":
                import webbrowser
                webbrowser.open("https://calendar.google.com/")
                return "Calendar opened"
            elif exe_name == "microsoft.windows.camera:":
                os.system("start microsoft.windows.camera:")
                return "Opened Camera"
            else:
                os.system(f"start {exe_name}")
                nice_name = app_name.title()
                if nice_name == "Vscode":
                    nice_name = "VS Code"
                elif nice_name == "Vs Code":
                    nice_name = "VS Code"
                return f"Opened {nice_name}"
        else:
            return f"I am sorry, but I am not able to open {app_name} as it is not installed or configured on this PC."

    # Handle close applications
    close_match = re.match(r"^(close|terminate|stop|exit|kill)\s+(.*)$", text)
    if close_match:
        app_name = clean_app_name(close_match.group(2).strip())
        if app_name in ["youtube", "you tube", "youtub", "music", "song", "video"]:
            try:
                # pyrefly: ignore [missing-import]
                import pygetwindow as gw
                import pyautogui
                import time as t
                windows = gw.getWindowsWithTitle("YouTube")
                if windows:
                    for w in windows:
                        try:
                            w.activate()
                            t.sleep(0.5)
                            pyautogui.hotkey('ctrl', 'w')
                        except Exception:
                            pass
                    return "Closed YouTube tab(s)"
                browser_windows = []
                for title in ["Edge", "Chrome", "Brave", "Firefox"]:
                    browser_windows.extend(gw.getWindowsWithTitle(title))
                closed = False
                for w in browser_windows:
                    try:
                        w.activate()
                        t.sleep(0.5)
                        for _ in range(15):
                            active_window = gw.getActiveWindow()
                            if active_window and "YouTube" in active_window.title:
                                pyautogui.hotkey('ctrl', 'w')
                                closed = True
                                break
                            pyautogui.hotkey('ctrl', 'tab')
                            t.sleep(0.2)
                        if closed:
                            break
                    except Exception:
                        continue
                if closed:
                    return "Closed YouTube tab"
                return "No YouTube window found"
            except Exception as e:
                return f"Could not close YouTube: {str(e)}"
                
        elif app_name in ["calendar", "google calendar"]:
            try:
                # pyrefly: ignore [missing-import]
                import pygetwindow as gw
                import pyautogui
                import time as t
                windows = []
                for title in ["Google Calendar", "Calendar -", "- Calendar"]:
                    windows.extend(gw.getWindowsWithTitle(title))
                if windows:
                    for w in windows:
                        try:
                            w.activate()
                            t.sleep(0.5)
                            pyautogui.hotkey('ctrl', 'w')
                        except Exception:
                            pass
                    return "Closed Calendar tab(s)"
                return "No Calendar window found"
            except Exception as e:
                return f"Could not close Calendar: {str(e)}"
                
        else:
            app_map = {
                "chrome": ["chrome.exe"], "notepad": ["notepad.exe"], "word": ["winword.exe"],
                "vscode": ["code.exe"], "vs code": ["code.exe"], "calculator": ["CalculatorApp.exe", "Calculator.exe"],
                "powershell": ["powershell.exe"], "idle": ["pythonw.exe"], "edge": ["msedge.exe"],
                "vlc": ["vlc.exe"], "command prompt": ["cmd.exe"], "cmd": ["cmd.exe"]
            }
            if app_name in app_map:
                exe_names = app_map[app_name]
                for exe in exe_names:
                    os.system(f"taskkill /F /IM {exe}")
                return f"Closed {app_name}"
            else:
                return f"I am sorry, but I couldn't find a running instance of {app_name} to close."

    # Handle YouTube playback
    youtube_match = re.match(r"^(play|search youtube for|youtube play|search on youtube)\s+(.*)$", text)
    if youtube_match:
        video = youtube_match.group(2).strip()
        import requests
        import urllib.parse
        try:
            query = urllib.parse.quote(video)
            headers = {"User-Agent": "Mozilla/5.0"}
            search_url = f"https://www.youtube.com/results?search_query={query}"
            html = requests.get(search_url, headers=headers, timeout=10).text
            video_ids = re.findall(r'"videoId":"(.*?)"', html)
            if not video_ids:
                return "❌ No video found"
            first_video_id = video_ids[0]
            video_url = f"https://www.youtube.com/watch?v={first_video_id}&autoplay=1"
            import time as t
            import pyautogui
            subprocess.Popen(f'start "" "{video_url}"', shell=True)
            t.sleep(3.5)
            pyautogui.press("k")
            pyautogui.press("space")
            return f"▶ Playing {video}"
        except Exception as e:
            return f"❌ {str(e)}"

    # Handle PC power
    if text == "shutdown pc" or text == "shutdown computer" or text == "turn off computer":
        os.system("shutdown /s /t 1")
        return "Shutting down"
    if text == "restart pc" or text == "restart computer":
        os.system("shutdown /r /t 1")
        return "Restarting"

    # Handle quick reminders
    reminder_match = re.match(r"^(remind me to|remind me|reminder to|reminder)\s+(.*)$", text)
    if reminder_match:
        rem_text = reminder_match.group(2).strip()
        now = datetime.date.today()
        target_date = now
        lower_rem = rem_text.lower()
        if "tomorrow" in lower_rem:
            target_date = now + datetime.timedelta(days=1)
        elif "day after tomorrow" in lower_rem:
            target_date = now + datetime.timedelta(days=2)
        elif "next week" in lower_rem:
            target_date = now + datetime.timedelta(days=7)
        
        clean_text = rem_text
        clean_text = re.sub(r'\s+on\s+(today|tomorrow|yesterday|next week|day after tomorrow)', '', clean_text, flags=re.IGNORECASE).strip()
        clean_text = re.sub(r'\s+(today|tomorrow|yesterday|next week|day after tomorrow)', '', clean_text, flags=re.IGNORECASE).strip()
        if clean_text:
            clean_text = clean_text[0].upper() + clean_text[1:]
        else:
            clean_text = "Task"
        date_str = target_date.strftime("%Y-%m-%d")
        db_add_reminder(date_str, clean_text)
        return f"Reminder added for {target_date.strftime('%A, %d %B %Y')}: {clean_text}"

    return None

# -------- RAG HELPERS & ENDPOINTS --------

import random
from werkzeug.utils import secure_filename

@app.route("/api/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files["file"]
    chat_id = request.form.get("chat_id")
    
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400
        
    if not chat_id:
        return jsonify({"error": "No chat session ID provided"}), 400
        
    filename = secure_filename(file.filename)
    uploads_dir = os.path.join(os.getcwd(), "uploads")
    if not os.path.exists(uploads_dir):
        os.makedirs(uploads_dir)
        
    file_path = os.path.join(uploads_dir, f"{chat_id}_{filename}")
    file.save(file_path)
     
    try:
        ext = os.path.splitext(filename)[1].lower()
        if ext == ".txt":
            from langchain_community.document_loaders import TextLoader
            loader = TextLoader(file_path, encoding="utf-8")
            docs = loader.load()
        elif ext == ".pdf":
            from langchain_community.document_loaders import PyPDFLoader
            loader = PyPDFLoader(file_path)
            docs = loader.load()
        else:
            return jsonify({"error": "Unsupported file format. Only PDF and TXT are supported."}), 400
            
        if not docs:
            return jsonify({"error": "Unable to extract content from this file."}), 400
            
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        split_docs = text_splitter.split_documents(docs)
        
        if not split_docs:
            return jsonify({"error": "File contains no processable text chunks."}), 400
            
        # pyrefly: ignore [missing-import]
        from langchain_cohere import CohereEmbeddings
        from langchain_community.vectorstores import FAISS
        
        embedding = CohereEmbeddings(cohere_api_key=API_KEY, model="embed-english-v3.0")
        
        db = FAISS.from_documents(documents=split_docs, embedding=embedding)
        
        faiss_dir = os.path.join(os.getcwd(), "faiss_indexes")
        if not os.path.exists(faiss_dir):
            os.makedirs(faiss_dir)
            
        db.save_local(os.path.join(faiss_dir, f"{chat_id}_{filename}"))
        
        db_save_uploaded_file(chat_id, filename)
        
        try:
            os.remove(file_path)
        except Exception:
            pass
            
        return jsonify({
            "status": "success",
            "filename": filename,
            "chunks_count": len(split_docs)
        })
        
    except Exception as e:
        try:
            os.remove(file_path)
        except Exception:
            pass
        return jsonify({"error": f"Error indexing file: {str(e)}"}), 500

# -------- CORE CHAT LOGIC --------

def process_message(user_input, chat_history, mode="text", active_file=None, chat_id=None):
    clean_old_data()

    if mode == "speech":
        preprocessed = preprocess_speech_input(user_input)
        if preprocessed == "not_clearly_heard":
            return "I couldn't hear you clearly. Please repeat or speak again."
        user_input = preprocessed

    # Detect exit RAG commands to stop RAG mode
    exit_phrases = ["forget this topic", "stop", "exit this topic", "stop this topic", "forget document", "close document", "forget this file", "close file", "exit rag", "stop rag"]
    clean_input = user_input.lower().strip(" .!?")
    if active_file and (clean_input in exit_phrases or any(phrase in clean_input for phrase in ["forget this topic", "exit this topic", "close document", "close file", "forget document", "exit rag"])):
        return "CLEAR_ACTIVE_FILE_CONFIRMATION"

    # If there is an active file uploaded, strictly do the RAG flow!
    if active_file:
        faiss_path = os.path.join(os.getcwd(), "faiss_indexes", f"{chat_id}_{active_file}")
        if os.path.exists(faiss_path):
            try:
                # pyrefly: ignore [missing-import]
                from langchain_cohere import CohereEmbeddings
                from langchain_community.vectorstores import FAISS
                
                embedding = CohereEmbeddings(cohere_api_key=API_KEY, model="embed-english-v3.0")
                
                db = FAISS.load_local(faiss_path, embedding, allow_dangerous_deserialization=True)
                results = db.similarity_search(user_input, k=4)
                
                context_str = "\n\n".join([doc.page_content for doc in results])
                
                rag_prompt = f"""You are Jarvis, a smart AI assistant answering questions about the uploaded document "{active_file}".
Use the following extracted document context to answer the user's question.

---
DOCUMENT CONTEXT:
{context_str}
---

USER QUESTION: {user_input}

Answer the question clearly, concisely, and professionally based strictly on the context.
IMPORTANT: If the answer cannot be found in the provided DOCUMENT CONTEXT, or if the user is asking a general question not related to the document, you MUST respond EXACTLY with: "This information is not present in the document."
Do not use any external knowledge or add any extra sentences."""
                
                response = llm.invoke(rag_prompt)
                ai_reply = response.content if hasattr(response, "content") else str(response)
                return ai_reply
                
            except Exception as e:
                return f"Error querying document: {str(e)}"
        else:
            return "This information is not present in the document."

    local_res = try_local_command_execution(user_input)
    if local_res is not None:
        return local_res

    result = None
    if parse_send_email_command(user_input) is not None:
        result = send_email_fn(user_input)
    elif is_notepad_summary_command(user_input):
        last_assistant = next((item.get("message","") for item in reversed(chat_history) if item.get("role") == "assistant"), "")
        topic = extract_summary_topic(user_input, last_assistant)
        result = notepad_summary_fn(topic)
    elif is_trip_budget_question(user_input):
        budget_amount = extract_trip_budget(chat_history, user_input)
        if budget_amount:
            result = budget_amount
    elif is_trip_budget_statement(user_input):
        result = plan_trip_fn(user_input)
    elif is_trip_plan_command(user_input):
        result = plan_trip_fn(user_input)

    if result is None:
        memory_context = build_memory(chat_history)

        speech_hint = ""
        if mode == "speech":
            speech_hint = "\nNOTE: The user input is transcribed from speech and may contain phonetic, spelling, or slightly misheard words. Be smart and fuzzy-match their intent to the correct category."

        router_prompt = f"""
You are an intelligent AI router.
Previous Conversation: {memory_context}
Current User Input: {user_input}
{speech_hint}

Decide:
1. If user wants desktop action/tool execution (open apps, play youtube, create/delete/rename files, send email, trip planning, calculator, restart/shutdown pc, powershell commands, terminal commands, cmd commands, tasklist, dir, ipconfig, ping, python, pip, npm, git, music, songs, videos, youtube, date, time, close application, reminders) → return TOOL
2. If user wants normal AI conversation/question/help → return CHAT

Return ONLY: TOOL or CHAT
"""
        router = llm.invoke(router_prompt)
        route = (router.content.strip().upper() if hasattr(router, "content") else str(router).strip().upper())

        if route == "TOOL" and TOOLS_AVAILABLE:
            existing_files = get_existing_files()
            existing_files_str = ", ".join(existing_files) if existing_files else "None"
            response = agent.invoke({
                "messages": [
                    {
                        "role": "system",
                        "content": f"""
Previous Conversation: {memory_context}
You are a Desktop AI Assistant.
EXISTING FILES: {existing_files_str}

RULES:
1. Use tools for desktop actions
2. Use only ONE tool
3. Never loop tools
4. Keep response short
5. Trip planning → use plan_trip
6. YouTube → use play_youtube
7. File operations → use tools
8. Never open multiple browser tabs
9. Return only final result
10. Always return tool output directly
11. For terminal/powershell/cmd commands → ALWAYS use run_powershell tool
12. Never explain commands
13. Never simulate command output
14. To close application → use close_application tool
15. To stop music/youtube/song → use stop_youtube tool
16. To open any application → use open_application tool
17. For YouTube/video/music requests → ALWAYS pass FULL USER QUERY to play_youtube tool
18. To write or generate Python code in VS Code → ALWAYS use generate_code_in_vscode tool
19. To create or write summaries/notes in Notepad → ALWAYS use notepad_summary tool
"""
                    },
                    {"role": "user", "content": user_input}
                ]
            })

            result = "Done"
            if isinstance(response, dict) and "messages" in response:
                messages = response["messages"]
                for msg in reversed(messages):
                    if isinstance(msg, ToolMessage):
                        result = msg.content
                        break
                else:
                    for msg in reversed(messages):
                        if isinstance(msg, AIMessage):
                            result = msg.content
                            break
            else:
                result = str(response)
        else:
            greeting_pattern = r'\b(hi|hello|hey|good morning|good evening|good afternoon|greetings|howdy)\b'
            is_greeting = re.search(greeting_pattern, user_input.lower()) is not None

            speech_chat_hint = ""
            if mode == "speech":
                speech_chat_hint = "\nNOTE: This message was transcribed from speech. If there are phonetic mistakes, spelling errors, or garbled words, interpret what they naturally meant and respond to their core intent directly."

            if is_greeting:
                ai_response = llm.invoke(f"""
You are Jarvis, a smart desktop AI assistant.
User said a GREETING: {user_input}
{speech_chat_hint}
Respond with a NATURAL GREETING - just one short sentence.
Examples: "What can I do for you?", "How's it going? 😊", "Hey there! What's up?"
IMPORTANT: Do NOT ask "how can I help?" - be more natural. Keep it under 10 words. Be friendly and quick. Do NOT say "Hello!" as the first word.
""")
            else:
                ai_response = llm.invoke(f"""
You are Jarvis, a smart desktop AI assistant.
CURRENT USER MESSAGE: {user_input}
Previous conversation: {memory_context}
{speech_chat_hint}
RESPOND NATURALLY:
1. If user thanks you: Reply "You're welcome!" or "Glad I could help!" or "Anytime!"
2. If user says "yes" or "ok" alone: CONTINUE the previous discussion. Do NOT start with "How can I help?"
3. For questions and topics: Answer directly without greeting, keep responses concise, do NOT start with "Hello!" or any greeting
4. IMPORTANT RULES: NEVER start response with greeting words. Answer should be direct and helpful.
""")

            result = ai_response.content if hasattr(ai_response, "content") else str(ai_response)

    return result

# -------- FLASK ROUTES --------

@app.route("/")
def index():
    if "chat_id" not in session:
        session["chat_id"] = str(uuid.uuid4())
        session["chat_title"] = "New Chat"
        session["interaction_count"] = 0
        session["start_time"] = time.time()
    return render_template("index.html")

@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.json or {}
    user_input = data.get("message", "").strip()
    chat_id = data.get("chat_id", session.get("chat_id", str(uuid.uuid4())))
    mode = data.get("mode", "text")
    active_file = data.get("active_file")

    if not user_input:
        return jsonify({"error": "Empty message"}), 400

    session["interaction_count"] = session.get("interaction_count", 0) + 1

    chat_history = load_chat_messages(chat_id)

    clear_active_file = False
    try:
        result = process_message(user_input, chat_history, mode=mode, active_file=active_file, chat_id=chat_id)
        if result == "CLEAR_ACTIVE_FILE_CONFIRMATION":
            result = "I have successfully closed the active document and deactivated RAG mode. I am now back in normal chat mode and ready for desktop commands/tool automation! What else can I help you with?"
            clear_active_file = True
    except Exception as e:
        result = f"Error: {str(e)}"

    save_chat(chat_id, "user", user_input)
    save_chat(chat_id, "assistant", result)

    chat_title = session.get("chat_title", "New Chat")
    if chat_title == "New Chat":
        new_title = user_input[:70]
        session["chat_title"] = new_title
        create_chat_session(chat_id, new_title)

    return jsonify({"response": result, "chat_id": chat_id, "clear_active_file": clear_active_file})

@app.route("/api/chats/last_3_days")
def get_chats_last_3_days():
    conn = get_db()
    rows = conn.execute("""
        SELECT role, message, timestamp,
               date(timestamp) as chat_date
        FROM chats 
        WHERE timestamp >= datetime('now', '-3 days') 
        ORDER BY id ASC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/chats/last_2_days")
def get_chats_last_2_days():
    conn = get_db()
    rows = conn.execute("""
        SELECT role, message, timestamp,
               date(timestamp) as chat_date
        FROM chats 
        WHERE timestamp >= datetime('now', '-2 days') 
        ORDER BY id ASC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/chats/clear_all", methods=["POST"])
def clear_all_chats():
    conn = get_db()
    conn.execute("DELETE FROM chats")
    conn.execute("DELETE FROM chat_sessions")
    conn.execute("DELETE FROM uploaded_files")
    conn.commit()
    conn.close()

    try:
        import shutil
        faiss_dir = os.path.join(os.getcwd(), "faiss_indexes")
        if os.path.exists(faiss_dir):
            shutil.rmtree(faiss_dir)
    except Exception:
        pass
    return jsonify({"status": "ok"})

@app.route("/api/sessions")
def get_sessions():
    sessions_list = load_chat_sessions()
    return jsonify(sessions_list)

@app.route("/api/session/<chat_id>/messages")
def get_messages(chat_id):
    messages = load_chat_messages(chat_id)
    return jsonify(messages)

@app.route("/api/session/<chat_id>/uploaded_files")
def get_session_uploaded_files(chat_id):
    files = db_get_uploaded_files(chat_id)
    return jsonify(files)

@app.route("/api/session/<chat_id>/delete", methods=["POST"])
def delete_session(chat_id):
    delete_chat(chat_id)
    return jsonify({"status": "ok"})

@app.route("/api/session/<chat_id>/rename", methods=["POST"])
def rename_session(chat_id):
    data = request.json
    new_title = data.get("title", "")
    rename_chat(chat_id, new_title)
    return jsonify({"status": "ok"})

@app.route("/api/reminders")
def get_reminders():
    return jsonify(db_load_reminders())

@app.route("/api/reminders/delete/<int:rem_id>", methods=["POST"])
def delete_reminder(rem_id):
    db_delete_reminder(rem_id)
    return jsonify({"status": "ok"})

@app.route("/api/reminders/clear", methods=["POST"])
def clear_reminders():
    db_clear_reminders()
    return jsonify({"status": "ok"})

@app.route("/api/stats")
def get_stats():
    start_time = session.get("start_time", time.time())
    elapsed = int(time.time() - start_time)
    hours = elapsed // 3600
    minutes = (elapsed % 3600) // 60
    seconds = elapsed % 60
    return jsonify({
        "time": f"{hours}h {minutes}m {seconds}s",
        "interactions": session.get("interaction_count", 0)
    })

@app.route("/api/new_chat", methods=["POST"])
def new_chat():
    new_id = str(uuid.uuid4())
    session["chat_id"] = new_id
    session["chat_title"] = "New Chat"
    return jsonify({"chat_id": new_id})

if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)
