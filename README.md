# NextGen Desktop Automation AI

An advanced AI-powered desktop assistant built using Python, Flask, SQLite, and Cohere API. This project provides a conversational AI assistant capable of chat memory, reminders, file tracking, email automation, desktop actions, and intelligent assistant workflows.

---

#  Features

##  AI Conversation System

* Human-like conversational AI assistant
* Context-aware chat memory
* Multi-session chat management
* Smart response generation using Cohere API
* Dynamic system prompt behavior

##  Persistent Memory

* SQLite database integration
* Chat session history storage
* Message persistence
* File upload tracking
* Reminder storage system

##  Chat Management

* Create multiple chat sessions
* Rename chat sessions
* Delete chat sessions
* Load previous conversations

##  Reminder System

* Add reminders
* Delete reminders
* View reminder history
* Persistent reminder storage

##  Email Automation

* Send emails directly using SMTP
* Environment variable-based credentials
* MIME email formatting support

##  Desktop Automation

* Open applications
* Browser automation
* YouTube playback support
* PowerShell command execution
* File management support

##  Web-Based Interface

* Flask backend
* Interactive frontend UI
* JSON API responses
* Session handling support

---

# Technologies Used

## Backend

* Python
* Flask
* SQLite3
* Cohere API
* SMTP

## Frontend

* HTML
* CSS
* JavaScript

## Database

* SQLite Database

## Environment Management

* Python Dotenv

---

#  Project Structure

```bash
jarvis_flask/
│
├── app.py
├── index.html
├── requirements.txt
├── .env
├── chat_memory.db
├── open_and_prime_number.py
├── summary_agent_20260520_170941.txt
├── summary_and___about_ai_agent_20260521_170914.txt
└── .gitignore
```

---

# Installation

##  Clone Repository

```bash
git clone https://github.com/your-username/jarvis_flask.git
cd jarvis_flask
```

---

##  Create Virtual Environment

### Windows

```bash
python -m venv venv
venv\Scripts\activate
```

### Linux / Mac

```bash
python3 -m venv venv
source venv/bin/activate
```

---

##  Install Dependencies

```bash
pip install -r requirements.txt
```

If requirements file does not work properly:

```bash
pip install flask python-dotenv requests cohere
```

---

#  Environment Variables

Create a `.env` file in the project root:

```env
COHERE_API_KEY=your_cohere_api_key
EMAIL=your_email@gmail.com
EMAIL_PASSWORD=your_email_password
```

---

#  Run Project

```bash
python app.py
```

Open browser:

```bash
http://127.0.0.1:5000
```

---

#  AI Assistant Capabilities

The Jarvis assistant can:

* Answer questions
* Maintain conversational context
* Generate emails
* Execute desktop-related tasks
* Manage reminders
* Store chat history
* Handle multi-session memory
* Perform browser actions
* Help with coding/debugging
* Generate summaries
* Assist with planning and productivity

---

# Database Tables

## chat_sessions

Stores all chat session metadata.

## chats

Stores user and assistant conversations.

## reminders

Stores reminder details.

## uploaded_files

Stores uploaded file history.

---

#  Future Improvements

* Autonomous Task Execution
* Real-Time Internet Search
* Advanced File Analysis
* Multi-Agent Workflow System
* Docker Deployment
* Authentication System
* Cloud Deployment

---

#  Author

Kush Dalal.

---

#  Project Type

AI + Flask + NLP + Automation + Memory-Based Intelligent Assistant System
