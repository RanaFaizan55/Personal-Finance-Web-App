from __future__ import annotations

import hashlib
import os
import signal
import socket
import sqlite3
import subprocess
from calendar import monthrange
from datetime import datetime
from pathlib import Path
from time import sleep

from flask import Flask, g, has_app_context, redirect, render_template, request, session, url_for

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "life_hub.db"

app = Flask(__name__)
application = app
app.secret_key = "life-hub-secret-key-change-me"

CURRENCY_RATES = {
    "USD": 1.0,
    "EUR": 0.92,
    "GBP": 0.79,
    "INR": 83.2,
    "PKR": 278.0,
    "AED": 3.67,
    "JPY": 157.5,
    "AUD": 1.52,
    "CAD": 1.36,
}

CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "INR": "₹",
    "PKR": "₨",
    "AED": "د.إ",
    "JPY": "¥",
    "AUD": "A$",
    "CAD": "C$",
}


def hash_password(password: str) -> str:
    return hashlib.sha256(password.strip().encode("utf-8")).hexdigest()


def get_db() -> sqlite3.Connection:
    if not has_app_context():
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    if "db" not in g:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        g.db = conn
    return g.db


@app.teardown_appcontext
def close_db(_error):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            date TEXT NOT NULL,
            notes TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS investments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            return_rate REAL NOT NULL,
            date TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            date TEXT NOT NULL,
            location TEXT DEFAULT '',
            notes TEXT DEFAULT ''
        );

        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_DATE
        );

        CREATE TABLE IF NOT EXISTS budget_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            cash_on_hand REAL NOT NULL DEFAULT 0.0,
            currency TEXT NOT NULL DEFAULT 'USD'
        );
        """
    )

    columns = conn.execute("PRAGMA table_info(budget_settings)").fetchall()
    if columns and not any(column[1] == "currency" for column in columns):
        conn.execute("ALTER TABLE budget_settings ADD COLUMN currency TEXT NOT NULL DEFAULT 'USD'")

    user_count = conn.execute("SELECT COUNT(*) AS total FROM users").fetchone()[0]
    if user_count == 0:
        conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            ("admin", hash_password("admin123")),
        )

    expense_count = conn.execute("SELECT COUNT(*) AS total FROM expenses").fetchone()[0]
    if expense_count == 0:
        seed_date = datetime.today()
        examples = [
            ("Groceries", "Food", 145.5, (seed_date.replace(day=7)).strftime("%Y-%m-%d"), "Weekly shopping"),
            ("Internet Bill", "Utilities", 70.0, (seed_date.replace(day=5)).strftime("%Y-%m-%d"), "Home internet"),
            ("Fuel", "Transport", 55.25, (seed_date.replace(day=2)).strftime("%Y-%m-%d"), "Commute"),
            ("Gym Membership", "Health", 42.0, (seed_date.replace(day=9)).strftime("%Y-%m-%d"), "Monthly wellness"),
        ]
        conn.executemany(
            "INSERT INTO expenses (title, category, amount, date, notes) VALUES (?, ?, ?, ?, ?)",
            examples,
        )

    investment_count = conn.execute("SELECT COUNT(*) AS total FROM investments").fetchone()[0]
    if investment_count == 0:
        seed_date = datetime.today()
        conn.executemany(
            "INSERT INTO investments (name, type, amount, return_rate, date) VALUES (?, ?, ?, ?, ?)",
            [
                ("Index Fund", "Mutual Fund", 6000.0, 8.4, (seed_date.replace(day=1)).strftime("%Y-%m-%d")),
                ("ETF Growth", "ETF", 3500.0, 9.7, (seed_date.replace(day=3)).strftime("%Y-%m-%d")),
            ],
        )

    event_count = conn.execute("SELECT COUNT(*) AS total FROM events").fetchone()[0]
    if event_count == 0:
        seed_date = datetime.today()
        conn.executemany(
            "INSERT INTO events (title, date, location, notes) VALUES (?, ?, ?, ?)",
            [
                ("Birthday Dinner", (seed_date.replace(day=min(seed_date.day + 12, 28))).strftime("%Y-%m-%d"), "Downtown", "Dinner reservation at 8:00 PM."),
                ("Annual Review", (seed_date.replace(day=min(seed_date.day + 18, 28))).strftime("%Y-%m-%d"), "Office", "Prepare performance notes."),
            ],
        )

    note_count = conn.execute("SELECT COUNT(*) AS total FROM notes").fetchone()[0]
    if note_count == 0:
        conn.executemany(
            "INSERT INTO notes (text, created_at) VALUES (?, ?)",
            [
                ("Set aside $500 for the emergency fund this month.", datetime.today().strftime("%Y-%m-%d")),
                ("Review subscriptions before the weekend.", datetime.today().strftime("%Y-%m-%d")),
            ],
        )

    conn.execute("UPDATE budget_settings SET currency = COALESCE(currency, 'USD') WHERE currency IS NULL OR currency = ''")

    budget_count = conn.execute("SELECT COUNT(*) AS total FROM budget_settings").fetchone()[0]
    if budget_count == 0:
        conn.execute("INSERT INTO budget_settings (cash_on_hand, currency) VALUES (?, ?)", (8500.0, "USD"))

    conn.commit()
    conn.close()


init_db()


def get_currency_code() -> str:
    row = get_db().execute(
        "SELECT currency FROM budget_settings ORDER BY id DESC LIMIT 1"
    ).fetchone()
    value = (row["currency"] if row and row["currency"] else "USD").upper()
    return value if value in CURRENCY_RATES else "USD"


def set_currency_code(code: str) -> str:
    cleaned = (code or "USD").strip().upper()
    selected = cleaned if cleaned in CURRENCY_RATES else "USD"
    get_db().execute("UPDATE budget_settings SET currency = ? WHERE id = (SELECT id FROM budget_settings ORDER BY id DESC LIMIT 1)", (selected,))
    if get_db().execute("SELECT changes() AS changed").fetchone()["changed"] == 0:
        get_db().execute("INSERT INTO budget_settings (cash_on_hand, currency) VALUES (?, ?)", (get_cash_on_hand(), selected))
    get_db().commit()
    return selected


def get_cash_on_hand() -> float:
    row = get_db().execute(
        "SELECT cash_on_hand FROM budget_settings ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return float(row["cash_on_hand"]) if row else 8500.0


def set_cash_on_hand(amount: float, currency: str | None = None) -> float:
    value = max(0.0, float(amount or 0))
    selected_currency = (currency or get_currency_code()).upper()
    if selected_currency not in CURRENCY_RATES:
        selected_currency = "USD"
    get_db().execute("DELETE FROM budget_settings")
    get_db().execute("INSERT INTO budget_settings (cash_on_hand, currency) VALUES (?, ?)", (value, selected_currency))
    get_db().commit()
    return value


def reset_all_data() -> None:
    use_context = has_app_context()
    conn = get_db() if use_context else sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        current_currency = conn.execute(
            "SELECT currency FROM budget_settings ORDER BY id DESC LIMIT 1"
        ).fetchone()
        selected_currency = (current_currency["currency"] if current_currency and current_currency["currency"] else "USD").upper()
        if selected_currency not in CURRENCY_RATES:
            selected_currency = "USD"

        conn.execute("DELETE FROM notes")
        conn.execute("DELETE FROM events")
        conn.execute("DELETE FROM investments")
        conn.execute("DELETE FROM expenses")
        conn.execute("DELETE FROM budget_settings")
        conn.execute(
            "INSERT INTO budget_settings (cash_on_hand, currency) VALUES (?, ?)",
            (0.0, selected_currency),
        )
        conn.commit()
    finally:
        if not use_context:
            conn.close()


def format_currency(value: float | int, currency: str | None = None) -> str:
    code = (currency or get_currency_code()).upper()
    code = code if code in CURRENCY_RATES else "USD"
    amount = float(value or 0)
    converted = amount * CURRENCY_RATES.get(code, 1.0)
    symbol = CURRENCY_SYMBOLS.get(code, "$")
    return f"{symbol}{converted:,.2f}"


app.jinja_env.globals["format_money"] = format_currency


def ensure_clean_port(port: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            try:
                out = subprocess.check_output(
                    ["lsof", "-t", "-i", f"TCP:{port}", "-sTCP:LISTEN"],
                    stderr=subprocess.DEVNULL,
                    text=True,
                )
            except (FileNotFoundError, subprocess.CalledProcessError):
                return

            for pid in [item.strip() for item in out.splitlines() if item.strip()]:
                try:
                    with open(f"/proc/{pid}/cmdline", "rb") as handle:
                        cmd = handle.read().decode("utf-8", "ignore")
                except OSError:
                    continue
                if "Prac.py" in cmd or "python" in cmd.lower():
                    try:
                        os.kill(int(pid), signal.SIGTERM)
                        sleep(0.3)
                        os.kill(int(pid), signal.SIGKILL)
                    except OSError:
                        pass
            sleep(0.5)


def fetch_all(table: str, order_by: str = "id DESC") -> list[dict]:
    allowed = {"users", "expenses", "investments", "events", "notes"}
    if table not in allowed:
        return []
    rows = get_db().execute(f"SELECT * FROM {table} ORDER BY {order_by}").fetchall()
    return [dict(row) for row in rows]


def category_palette() -> list[str]:
    return ["#7c9cff", "#4ade80", "#fbbf24", "#a78bfa", "#f87171", "#22d3ee", "#fb7185", "#c084fc"]


def expense_by_category(expenses: list[dict]) -> list[dict]:
    totals: dict[str, float] = {}
    for item in expenses:
        category = item.get("category", "General")
        totals[category] = totals.get(category, 0.0) + float(item.get("amount", 0) or 0)

    total_amount = sum(totals.values())
    categories: list[dict] = []
    for index, (category, amount) in enumerate(sorted(totals.items(), key=lambda entry: entry[1], reverse=True)):
        percent = round((amount / total_amount) * 100, 1) if total_amount else 0
        categories.append({
            "category": category,
            "amount": round(amount, 2),
            "percent": percent,
            "color": category_palette()[index % len(category_palette())],
        })
    return categories


def monthly_totals(expenses: list[dict], months: int = 6) -> list[dict]:
    now = datetime.today()
    totals: list[dict] = []
    for offset in range(months - 1, -1, -1):
        month_date = now.month - offset
        year = now.year
        while month_date <= 0:
            year -= 1
            month_date += 12
        while month_date > 12:
            year += 1
            month_date -= 12

        month_total = 0.0
        for expense in expenses:
            date_value = expense.get("date")
            if not date_value:
                continue
            try:
                expense_date = datetime.strptime(date_value, "%Y-%m-%d")
            except ValueError:
                continue
            if expense_date.year == year and expense_date.month == month_date:
                month_total += float(expense.get("amount", 0) or 0)

        totals.append({
            "label": datetime(year, month_date, 1).strftime("%b"),
            "total": round(month_total, 2),
        })
    return totals


def build_month_calendar(year: int, month: int, events: list[dict], expenses: list[dict]):
    first_day = datetime(year, month, 1)
    days_in_month = monthrange(year, month)[1]
    first_weekday = first_day.weekday()
    prev_month = month - 1 if month > 1 else 12
    prev_year = year if month > 1 else year - 1
    prev_days = monthrange(prev_year, prev_month)[1]

    event_map: dict[str, list[dict]] = {}
    for event in events:
        event_map.setdefault(event.get("date"), []).append(event)

    expense_map: dict[str, list[dict]] = {}
    for item in expenses:
        expense_map.setdefault(item.get("date"), []).append(item)

    cells: list[dict] = []
    for day_offset in range(1, first_weekday + 1):
        cells.append({
            "day": prev_days - first_weekday + day_offset,
            "is_current_month": False,
            "is_today": False,
            "date": "",
            "events": [],
            "expenses": [],
        })

    for day in range(1, days_in_month + 1):
        date_value = datetime(year, month, day).strftime("%Y-%m-%d")
        cells.append({
            "day": day,
            "is_current_month": True,
            "is_today": date_value == datetime.today().strftime("%Y-%m-%d"),
            "date": date_value,
            "events": event_map.get(date_value, []),
            "expenses": expense_map.get(date_value, []),
        })

    while len(cells) % 7 != 0:
        next_day = len(cells) - sum(1 for cell in cells if cell["is_current_month"]) + 1
        cells.append({
            "day": next_day,
            "is_current_month": False,
            "is_today": False,
            "date": "",
            "events": [],
            "expenses": [],
        })

    return [cells[index : index + 7] for index in range(0, len(cells), 7)]


def compute_summary(expenses: list[dict], investments: list[dict], events: list[dict], cash_on_hand: float | None = None, currency: str | None = None) -> dict:
    total_expenses = sum(float(item.get("amount", 0) or 0) for item in expenses)
    total_investments = sum(float(item.get("amount", 0) or 0) for item in investments)
    selected_currency = (currency or get_currency_code()).upper()
    cash = float(cash_on_hand) if cash_on_hand is not None else get_cash_on_hand()
    remaining_budget = cash - total_expenses
    upcoming_events = sorted(events, key=lambda item: item["date"])
    next_event = upcoming_events[0] if upcoming_events else None
    budget_percentage = min(100, max(0, (total_expenses / cash) * 100)) if cash else 0

    return {
        "total_expenses": round(total_expenses, 2),
        "total_investments": round(total_investments, 2),
        "remaining_budget": round(remaining_budget, 2),
        "cash_in_hand": round(cash, 2),
        "event_count": len(upcoming_events),
        "next_event": next_event,
        "monthly_budget": cash,
        "budget_percentage": round(budget_percentage, 1),
        "currency": selected_currency,
    }


def current_month_params() -> tuple[int, int]:
    today = datetime.today()
    year = int(request.args.get("year", today.year))
    month = int(request.args.get("month", today.month))
    if month < 1:
        month = 12
        year -= 1
    if month > 12:
        month = 1
        year += 1
    return year, month


def login_required(view):
    def wrapped(*args, **kwargs):
        if "user" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    wrapped.__name__ = view.__name__
    return wrapped


@app.route("/")
def index():
    if "user" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if "user" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        row = get_db().execute(
            "SELECT * FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if row and row["password_hash"] == hash_password(password):
            session["user"] = username
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Invalid username or password.")

    return render_template("login.html", error=None)


@app.route("/register", methods=["GET", "POST"])
def register():
    if "user" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not username or len(username) < 3:
            return render_template("register.html", error="Username must be at least 3 characters.")
        if len(password) < 4:
            return render_template("register.html", error="Password must be at least 4 characters.")
        if password != confirm:
            return render_template("register.html", error="Passwords do not match.")

        existing = get_db().execute(
            "SELECT 1 FROM users WHERE LOWER(username) = LOWER(?)",
            (username,),
        ).fetchone()
        if existing:
            return render_template("register.html", error="That username is already taken.")

        get_db().execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(password)),
        )
        get_db().commit()
        session["user"] = username
        return redirect(url_for("dashboard"))

    return render_template("register.html", error=None)


@app.route("/logout")
def logout():
    session.pop("user", None)
    return redirect(url_for("login"))


@app.route("/budget/update", methods=["POST"])
@login_required
def update_budget():
    cash_value = request.form.get("cash_on_hand")
    currency_code = request.form.get("currency")
    if currency_code:
        set_currency_code(currency_code)
    if cash_value is not None:
        try:
            set_cash_on_hand(float(cash_value), currency=currency_code or get_currency_code())
        except ValueError:
            pass
    return redirect(url_for("dashboard"))


@app.route("/reset-all", methods=["POST"])
@login_required
def reset_all():
    reset_all_data()
    return redirect(url_for("dashboard"))


@app.route("/dashboard")
@login_required
def dashboard():
    expenses = fetch_all("expenses", "date DESC, id DESC")
    investments = fetch_all("investments", "date DESC, id DESC")
    events = fetch_all("events", "date ASC, id ASC")
    active_currency = get_currency_code()
    summary = compute_summary(expenses, investments, events, cash_on_hand=get_cash_on_hand(), currency=active_currency)
    year, month = current_month_params()
    calendar_weeks = build_month_calendar(year, month, events, expenses)
    month_name = datetime(year, month, 1).strftime("%B %Y")

    return render_template(
        "dashboard.html",
        page_title="Dashboard",
        user=session.get("user", "User"),
        today=datetime.today().strftime("%Y-%m-%d"),
        summary=summary,
        expenses=expenses[:5],
        investments=investments[:5],
        events=events[:4],
        monthly_totals=monthly_totals(expenses),
        category_breakdown=expense_by_category(expenses),
        budget_percentage=summary["budget_percentage"],
        currency=active_currency,
        currency_symbol=CURRENCY_SYMBOLS.get(active_currency, "$"),
        calendar_weeks=calendar_weeks,
        month_name=month_name,
        year=year,
        month=month,
        prev_month=month - 1 if month > 1 else 12,
        prev_year=year if month > 1 else year - 1,
        next_month=month + 1 if month < 12 else 1,
        next_year=year if month < 12 else year + 1,
    )


@app.route("/analytics")
@login_required
def analytics():
    expenses = fetch_all("expenses", "date DESC, id DESC")
    investments = fetch_all("investments", "date DESC, id DESC")
    events = fetch_all("events", "date ASC, id ASC")
    active_currency = get_currency_code()
    summary = compute_summary(expenses, investments, events, cash_on_hand=get_cash_on_hand(), currency=active_currency)
    breakdown = expense_by_category(expenses)
    return render_template(
        "analytics.html",
        page_title="Analytics",
        user=session.get("user", "User"),
        summary=summary,
        monthly_totals=monthly_totals(expenses),
        category_breakdown=breakdown,
        budget_percentage=summary["budget_percentage"],
        currency=active_currency,
        currency_symbol=CURRENCY_SYMBOLS.get(active_currency, "$"),
        today=datetime.today().strftime("%Y-%m-%d"),
    )


@app.route("/expenses", methods=["GET", "POST"])
@login_required
def expenses_page():
    if request.method == "POST":
        title = request.form.get("title", "Expense").strip() or "Expense"
        category = request.form.get("category", "General").strip() or "General"
        amount = float(request.form.get("amount", 0) or 0)
        date_value = request.form.get("date") or datetime.today().strftime("%Y-%m-%d")
        notes = request.form.get("notes", "").strip()
        get_db().execute(
            "INSERT INTO expenses (title, category, amount, date, notes) VALUES (?, ?, ?, ?, ?)",
            (title, category, amount, date_value, notes),
        )
        get_db().commit()
        return redirect(url_for("expenses_page"))

    items = fetch_all("expenses", "date DESC, id DESC")
    active_currency = get_currency_code()
    return render_template(
        "expenses.html",
        page_title="Expenses",
        user=session.get("user", "User"),
        expenses=items,
        today=datetime.today().strftime("%Y-%m-%d"),
        currency=active_currency,
        currency_symbol=CURRENCY_SYMBOLS.get(active_currency, "$"),
    )


@app.route("/investments", methods=["GET", "POST"])
@login_required
def investments_page():
    if request.method == "POST":
        name = request.form.get("name", "Investment").strip() or "Investment"
        type_name = request.form.get("type", "General").strip() or "General"
        amount = float(request.form.get("amount", 0) or 0)
        return_rate = float(request.form.get("return_rate", 0) or 0)
        date_value = request.form.get("date") or datetime.today().strftime("%Y-%m-%d")
        get_db().execute(
            "INSERT INTO investments (name, type, amount, return_rate, date) VALUES (?, ?, ?, ?, ?)",
            (name, type_name, amount, return_rate, date_value),
        )
        get_db().commit()
        return redirect(url_for("investments_page"))

    items = fetch_all("investments", "date DESC, id DESC")
    active_currency = get_currency_code()
    return render_template(
        "investments.html",
        page_title="Investments",
        user=session.get("user", "User"),
        investments=items,
        today=datetime.today().strftime("%Y-%m-%d"),
        currency=active_currency,
        currency_symbol=CURRENCY_SYMBOLS.get(active_currency, "$"),
    )


@app.route("/events", methods=["GET", "POST"])
@login_required
def events_page():
    if request.method == "POST":
        title = request.form.get("title", "Event").strip() or "Event"
        date_value = request.form.get("date") or datetime.today().strftime("%Y-%m-%d")
        location = request.form.get("location", "TBD").strip() or "TBD"
        notes = request.form.get("notes", "").strip()
        get_db().execute(
            "INSERT INTO events (title, date, location, notes) VALUES (?, ?, ?, ?)",
            (title, date_value, location, notes),
        )
        get_db().commit()
        return redirect(url_for("events_page"))

    items = fetch_all("events", "date ASC, id ASC")
    return render_template(
        "events.html",
        page_title="Events",
        user=session.get("user", "User"),
        events=items,
        today=datetime.today().strftime("%Y-%m-%d"),
    )


@app.route("/notes", methods=["GET", "POST"])
@login_required
def notes_page():
    if request.method == "POST":
        text = request.form.get("note_text", "").strip()
        if text:
            get_db().execute(
                "INSERT INTO notes (text, created_at) VALUES (?, ?)",
                (text, datetime.today().strftime("%Y-%m-%d")),
            )
            get_db().commit()
        return redirect(url_for("notes_page"))

    items = fetch_all("notes", "id DESC")
    return render_template(
        "notes.html",
        page_title="Notes",
        user=session.get("user", "User"),
        notes=items,
    )


@app.route("/delete/<collection>/<int:item_id>", methods=["POST"])
@login_required
def delete_item(collection: str, item_id: int):
    allowed = {"expenses", "investments", "events", "notes"}
    if collection in allowed:
        get_db().execute(f"DELETE FROM {collection} WHERE id = ?", (item_id,))
        get_db().commit()
    return redirect(request.referrer or url_for("dashboard"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5001"))
    ensure_clean_port(port)
    app.run(debug=False, host="0.0.0.0", port=port, use_reloader=False)
