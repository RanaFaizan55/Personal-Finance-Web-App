# Personal Finance Web App

A premium personal finance and life-management dashboard built with Flask and SQLite.

## Features

- Dashboard overview with cash on hand and remaining budget
- Expense tracking by category
- Investment tracking with return-rate insights
- Event planner and monthly calendar
- Notes and personal reminders
- Authentication with login/register flow
- Multi-currency support
- Light/dark theme toggle
- Reset controls for quick resets to zero
- SQLite data persistence

## Tech Stack

- Python
- Flask
- SQLite
- Jinja2
- HTML/CSS/JavaScript

## Project Structure

- `Prac.py` — main Flask app and logic
- `static/` — CSS and JS assets
- `templates/` — HTML pages
- `data/` — SQLite database and local JSON storage files

## Setup

1. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

3. Run the app:
   ```bash
   python3 app.py
   ```

   The project also keeps a compatibility entrypoint at `Prac.py` for older hosting setups.

4. Open in browser:
   ```text
   http://127.0.0.1:5001
   ```

## Default Login

- Username: `admin`
- Password: `admin123`

## Notes

The app is designed for local use and keeps data in SQLite for persistent tracking.
