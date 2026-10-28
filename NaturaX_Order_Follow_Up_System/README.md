# NaturaX Order Follow-up System

A standalone Django web application for finding D2C orders that need attention and tracking follow-up through resolution. It replaces manual spreadsheet checking with data validation, configurable exception rules, assigned tasks, deadlines, dashboard summaries, daily reports, and an audit trail.

## Requirements

- Windows 10 or later
- Python 3.10 or later, available as `py` or `python` in PowerShell
- Internet access on the first run to install Python packages

## Quick start on Windows

1. Extract `NaturaX_Order_Follow_Up_System.zip`.
2. Open the extracted `NaturaX_Order_Follow_Up_System` folder.
3. Double-click `run.bat`.
4. When the server starts, open <http://127.0.0.1:8000/> in your browser.
5. Keep the command window open while using the app. Press **Ctrl+C** there to stop the server.

The first run creates a virtual environment, installs requirements, and creates the database. Later runs reuse the environment and database.

## Manual setup

Open PowerShell in the extracted project directory and run:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Then visit <http://127.0.0.1:8000/>. To stop the server, press **Ctrl+C**.

## Demo workflow

1. Open **Upload data** and either upload a CSV or Excel file or click **Load sample dataset**.
2. Review the import summary and any data issues reported for the latest upload.
3. Use **Dashboard** to review orders requiring attention, open tasks, overdue tasks, exception categories, employee workload, and high-priority cases.
4. Open **Tasks** to update task status. The manager can reassign a task.
5. Open **Daily report** to review new, unresolved, overdue, and high-priority exceptions. Use **Download CSV** to export it.
6. Open **Audit trail** to see recorded assignments, status changes, reassignments, uploads, and rule-setting changes.
7. Open **Rules & settings** to adjust the unconfirmed-order limit, dispatch-delay limit, high-value threshold, or simulated clock.
8. On **Tasks**, choose **Draft customer message** to generate an unsent message for the manager or assigned employee to review. On the **Dashboard**, choose **Generate AI daily brief** for a manager-facing summary of the current unresolved workload.
9. Open **AI Copilot** as the manager to ask about the current workload and the exception playbooks.

## Optional AI features

AI features use Google's Gemini API. They are optional; all non-AI order, task, reporting, and audit features work without an API key.

1. Create a Gemini API key in [Google AI Studio](https://aistudio.google.com/app/apikey).
2. Copy `.env.example` to `.env` in this directory.
3. Open `.env` and set `GEMINI_API_KEY` to your key. The default model is `gemini-3.5-flash-lite`; change `GEMINI_MODEL` only if you have access to another model.
4. Install updated requirements with `python -m pip install -r requirements.txt`, apply migrations with `python manage.py migrate`, and create the playbook embedding index with `python manage.py index_knowledge`.
5. Start the server with `python manage.py runserver`.

Keep `.env` private and do not include your real API key in a submission or source-control repository. Google's free-tier terms may allow submitted data to be used to improve its products; do not use real sensitive customer information with the free tier. If the key is missing or the API request fails, the app displays an error and does not send a message or alter task data.

The project includes three AI features: customer follow-up drafts, a daily operations brief, and a manager-only AI Copilot. The Copilot uses Gemini function calling to select from a fixed set of read-only Django ORM tools that return aggregate exception counts; model-supplied SQL and arbitrary database lookups are not accepted. RAG retrieves relevant generic exception playbooks using Gemini embeddings stored in the local SQLite database. Re-run `python manage.py index_knowledge` after changing the playbook guidance.

AI prompts do not include customer names, phone numbers, order IDs, or employee names. Customer drafts use local placeholders that the app fills in after Gemini returns the text. The daily brief sends aggregate task counts only. Copilot prompts and responses are not stored; the audit trail records only that it was used. Generated customer text is never sent automatically and must be reviewed by an employee. Gemini embedding and generation requests require a working API key and available model quota; all non-AI features work without one.

For a repeatable demonstration using `sample_data/sample_orders.csv`, load the sample dataset. This also sets the simulated clock to **21 October 2026 at 10:00**. For another dataset, set the simulated clock under **Rules & settings** before uploading if you want a repeatable result.

## Business rules

- Unconfirmed orders are flagged after the configured number of hours (default: 2).
- Confirmed orders with no dispatch date are flagged after the configured dispatch limit (default: 24 hours from order time).
- Dispatched orders are flagged when their expected delivery date has passed.
- Failed delivery attempts create an immediate high-priority task.
- Undelivered orders above the configured value threshold (default: ₹5,000) are flagged after the expected delivery date.

Each exception includes a reason, priority, recommended action, assignee, and deadline. A rule only runs when the data it needs is available. Invalid or missing fields are reported on the upload page. Repeated uploads do not create a second task for the same order and rule.

## Data and project structure

- `manage.py` - Django command-line entry point
- `config/` - Django settings and web-server configuration
- `orders/` - Django models, migrations, views, URLs, and templates
- `rules.py` - exception evaluation logic
- `sample_data/sample_orders.csv` - demo dataset
- `requirements.txt` - Python package dependencies
- `.env.example` - template for optional AI API configuration
- `run.bat` - Windows setup and launch helper

The app creates `db.sqlite3` in this directory. The database persists orders, tasks, settings, uploads, data issues, and audit entries across refreshes and restarts.

## Demo account behavior

The **Acting as** selector simulates the manager and employee roles for demonstration. It is a user picker, not production authentication. The manager can edit rules and reassign tasks; employees can update their own task status.

## Current limitations

- Data is imported from files; there is no live order-system or courier integration.
- The app does not send WhatsApp messages, emails, or notifications.
- Employee selection is simulated rather than backed by real user accounts and permissions.
- SQLite is intended for this prototype and light local use.
- The app does not yet calculate all long-term effectiveness metrics, such as average resolution time or the percentage of tasks resolved before deadline.

## Production note

This is an assessment prototype. Before deploying it for real users, configure a secure secret key, set `DEBUG = False`, restrict allowed hosts, add real authentication, and use a production-grade database and web server.
