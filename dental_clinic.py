from datetime import datetime
from functools import wraps
from pathlib import Path
import os
import random
import sqlite3

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "database.db"
app = Flask(__name__, template_folder=str(BASE_DIR))
app.secret_key = os.environ.get("DENTAL_CLINIC_SECRET", "dental_clinic_secret_key_change_this")
ADMIN_USERNAME = os.environ.get("DENTAL_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("DENTAL_ADMIN_PASSWORD", "admin123")


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception=None):
    database = g.pop("db", None)
    if database is not None:
        database.close()


def init_db():
    database = sqlite3.connect(DATABASE)
    database.executescript(
        """
        PRAGMA foreign_keys = ON;
        CREATE TABLE IF NOT EXISTS patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            contact TEXT,
            address TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS doctors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            specialization TEXT,
            contact TEXT
        );
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            doctor_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'Scheduled',
            FOREIGN KEY (patient_id) REFERENCES patients(id),
            FOREIGN KEY (doctor_id) REFERENCES doctors(id)
        );
        CREATE TABLE IF NOT EXISTS bills (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'Unpaid',
            date TEXT NOT NULL,
            FOREIGN KEY (appointment_id) REFERENCES appointments(id),
            FOREIGN KEY (patient_id) REFERENCES patients(id)
        );
        """
    )
    if database.execute("SELECT COUNT(*) FROM doctors").fetchone()[0] == 0:
        database.executemany(
            "INSERT INTO doctors (name, specialization, contact) VALUES (?, ?, ?)",
            [("Dr. Sarah Williams", "General Dentistry", "555-0101"),
             ("Dr. Michael Chen", "Orthodontics", "555-0102")],
        )
    database.commit()
    database.close()


def login_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapper


def admin_required(view):
    @wraps(view)
    def wrapper(*args, **kwargs):
        if session.get("user_type") != "admin":
            flash("Admin access required.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapper


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        form = request.form
        name = form.get("name", "").strip()
        email = form.get("email", "").strip().lower()
        password = form.get("password", "")
        if not name or not email or not password:
            flash("Name, email, and password are required.", "error")
            return render_template("register.html")
        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("register.html")
        try:
            database = get_db()
            database.execute(
                """INSERT INTO patients (name, email, password, contact, address, created_at)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (name, email, generate_password_hash(password), form.get("contact", "").strip(),
                 form.get("address", "").strip(), datetime.now().isoformat(timespec="seconds")),
            )
            database.commit()
            flash("Registration successful! Please login.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already registered.", "error")
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        patient = get_db().execute(
            "SELECT * FROM patients WHERE email = ?", (email,)
        ).fetchone()
        if patient and check_password_hash(patient["password"], password):
            session.clear()
            session.update(user_id=patient["id"], user_type="patient", user_name=patient["name"])
            return redirect(url_for("dashboard"))
        flash("Invalid email or password.", "error")
    return render_template("login.html")


@app.route("/admin_login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        if (request.form.get("username") == ADMIN_USERNAME and
                request.form.get("password") == ADMIN_PASSWORD):
            session.clear()
            session.update(user_id=0, user_type="admin", user_name="Administrator")
            return redirect(url_for("dashboard"))
        flash("Invalid admin credentials.", "error")
    return render_template("admin_login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    database = get_db()
    if session["user_type"] == "patient":
        stats = database.execute(
            """SELECT COUNT(*) AS total,
            SUM(CASE WHEN status = 'Scheduled' THEN 1 ELSE 0 END) AS scheduled
            FROM appointments WHERE patient_id = ?""",
            (session["user_id"],),
        ).fetchone()
    else:
        stats = database.execute(
            """SELECT COUNT(*) AS total,
            SUM(CASE WHEN status = 'Scheduled' THEN 1 ELSE 0 END) AS scheduled
            FROM appointments"""
        ).fetchone()
    return render_template(
        "dashboard.html", user_name=session["user_name"],
        user_type=session["user_type"], stats=stats,
    )


@app.route("/doctors")
@login_required
def doctors():
    rows = get_db().execute("SELECT * FROM doctors ORDER BY name").fetchall()
    return render_template("doctors.html", doctors=rows)


@app.route("/appointments", methods=["GET", "POST"])
@login_required
def appointments():
    if session.get("user_type") != "patient":
        flash("Only patients can book appointments.", "error")
        return redirect(url_for("dashboard"))
    database = get_db()
    doctors_list = database.execute("SELECT * FROM doctors ORDER BY name").fetchall()
    if request.method == "POST":
        form = request.form
        doctor_id = form.get("doctor_id")
        if not doctor_id:
            doctor = database.execute(
                "SELECT id FROM doctors WHERE name = ?", (form.get("doctor_name"),)
            ).fetchone()
            doctor_id = doctor["id"] if doctor else None
        if not doctor_id:
            flash("Please select a valid doctor.", "error")
            return render_template("appoinments.html", doctors=doctors_list)
        doctor = database.execute("SELECT id FROM doctors WHERE id = ?", (doctor_id,)).fetchone()
        if not doctor:
            flash("Please select a valid doctor.", "error")
            return render_template("appoinments.html", doctors=doctors_list)
        appointment_date = form.get("date") or form.get("appointment_date")
        appointment_time = form.get("time") or form.get("appointment_time")
        if not appointment_date or not appointment_time or not form.get("reason", "").strip():
            flash("Date, time, and reason are required.", "error")
            return render_template("appoinments.html", doctors=doctors_list)
        try:
            parsed_date = datetime.strptime(appointment_date, "%Y-%m-%d").date()
            datetime.strptime(appointment_time, "%H:%M")
        except ValueError:
            flash("Please enter a valid date and time.", "error")
            return render_template("appoinments.html", doctors=doctors_list)
        if parsed_date < datetime.now().date():
            flash("Appointments must be booked for today or a future date.", "error")
            return render_template("appoinments.html", doctors=doctors_list)
        existing = database.execute(
            """SELECT id FROM appointments
            WHERE doctor_id = ? AND date = ? AND time = ? AND status = 'Scheduled'""",
            (doctor_id, appointment_date, appointment_time),
        ).fetchone()
        if existing:
            flash("That doctor is already booked for this time.", "error")
            return render_template("appoinments.html", doctors=doctors_list)
        cursor = database.execute(
            """INSERT INTO appointments (patient_id, doctor_id, date, time, reason, status)
            VALUES (?, ?, ?, ?, ?, 'Scheduled')""",
            (session["user_id"], doctor_id, appointment_date, appointment_time, form["reason"].strip()),
        )
        amount = random.choice([500, 800, 1000, 1500, 2000])
        database.execute(
            "INSERT INTO bills (appointment_id, patient_id, amount, status, date) VALUES (?, ?, ?, 'Unpaid', ?)",
            (cursor.lastrowid, session["user_id"], amount, datetime.now().strftime("%Y-%m-%d")),
        )
        database.commit()
        flash("Appointment booked successfully!", "success")
        return redirect(url_for("bill"))
    return render_template("appoinments.html", doctors=doctors_list)


@app.route("/my_appointments")
@login_required
def my_appointments():
    if session.get("user_type") != "patient":
        flash("Only patients have appointment history.", "error")
        return redirect(url_for("dashboard"))
    rows = get_db().execute(
        """SELECT appointments.id, doctors.name AS doctor_name,
        doctors.specialization, appointments.date, appointments.time,
        appointments.reason, appointments.status, bills.amount, bills.status AS bill_status
        FROM appointments JOIN doctors ON appointments.doctor_id = doctors.id
        LEFT JOIN bills ON bills.appointment_id = appointments.id
        WHERE appointments.patient_id = ? ORDER BY appointments.date DESC, appointments.time DESC""",
        (session["user_id"],),
    ).fetchall()
    return render_template("my_appointments.html", appointments=rows)


@app.route("/appointments/<int:appointment_id>/cancel", methods=["POST"])
@login_required
def cancel_appointment(appointment_id):
    database = get_db()
    appointment = database.execute(
        "SELECT status FROM appointments WHERE id = ? AND patient_id = ?",
        (appointment_id, session.get("user_id")),
    ).fetchone()
    if not appointment:
        flash("Appointment not found.", "error")
    elif appointment["status"] != "Scheduled":
        flash("Only scheduled appointments can be cancelled.", "error")
    else:
        database.execute("UPDATE appointments SET status = 'Cancelled' WHERE id = ?", (appointment_id,))
        database.commit()
        flash("Appointment cancelled.", "success")
    return redirect(url_for("my_appointments"))


@app.route("/bill")
@login_required
def bill():
    if session.get("user_type") != "patient":
        flash("Only patients have bills.", "error")
        return redirect(url_for("dashboard"))
    bill_data = get_db().execute(
        """SELECT bills.id AS bill_id, bills.amount, bills.status, bills.date,
        appointments.id AS appointment_id, patients.name AS patient_name
        FROM bills JOIN appointments ON bills.appointment_id = appointments.id
        JOIN patients ON bills.patient_id = patients.id
        WHERE bills.patient_id = ? ORDER BY bills.id DESC LIMIT 1""",
        (session["user_id"],),
    ).fetchone()
    if not bill_data:
        flash("No bills found. Book an appointment first.", "error")
        return redirect(url_for("dashboard"))
    return render_template("bill.html", bill=bill_data)


@app.route("/add_doctor", methods=["GET", "POST"])
@login_required
@admin_required
def add_doctor():
    if request.method == "POST":
        form = request.form
        name = form.get("name", "").strip()
        specialization = form.get("specialization", "").strip()
        contact = form.get("contact", "").strip()
        if not name or not specialization or not contact:
            flash("Doctor name, specialization, and contact are required.", "error")
            return render_template("add_doctor.html")
        database = get_db()
        database.execute(
            "INSERT INTO doctors (name, specialization, contact) VALUES (?, ?, ?)",
            (name, specialization, contact),
        )
        database.commit()
        flash("Doctor added successfully!", "success")
        return redirect(url_for("doctors"))
    return render_template("add_doctor.html")


@app.route("/patients")
@login_required
@admin_required
def patients():
    rows = get_db().execute("SELECT * FROM patients ORDER BY id").fetchall()
    return render_template("patients.html", patients=rows)


@app.route("/view_appointments")
@login_required
@admin_required
def view_appointments():
    rows = get_db().execute(
        """SELECT appointments.id, patients.name AS patient_name, doctors.name AS doctor_name,
        appointments.date, appointments.time, appointments.reason, appointments.status
        FROM appointments JOIN patients ON appointments.patient_id = patients.id
        JOIN doctors ON appointments.doctor_id = doctors.id ORDER BY appointments.id DESC"""
    ).fetchall()
    return render_template("view_appointments.html", appointments=rows)


@app.route("/appointments/<int:appointment_id>/status", methods=["POST"])
@login_required
@admin_required
def update_appointment_status(appointment_id):
    status = request.form.get("status")
    if status not in {"Scheduled", "Completed", "Cancelled"}:
        flash("Invalid appointment status.", "error")
    else:
        database = get_db()
        result = database.execute(
            "UPDATE appointments SET status = ? WHERE id = ?", (status, appointment_id)
        )
        if result.rowcount == 0:
            flash("Appointment not found.", "error")
            return redirect(url_for("view_appointments"))
        database.commit()
        flash("Appointment status updated.", "success")
    return redirect(url_for("view_appointments"))


@app.route("/reports")
@login_required
@admin_required
def reports():
    database = get_db()
    summary = database.execute(
        """SELECT COUNT(*) AS appointments,
        SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) AS completed,
        SUM(CASE WHEN status = 'Scheduled' THEN 1 ELSE 0 END) AS scheduled,
        SUM(CASE WHEN status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled
        FROM appointments"""
    ).fetchone()
    billing = database.execute(
        """SELECT COALESCE(SUM(amount), 0) AS billed,
        COALESCE(SUM(CASE WHEN status = 'Paid' THEN amount ELSE 0 END), 0) AS paid,
        COALESCE(SUM(CASE WHEN status = 'Unpaid' THEN amount ELSE 0 END), 0) AS outstanding
        FROM bills"""
    ).fetchone()
    recent = database.execute(
        """SELECT patients.name AS patient_name, doctors.name AS doctor_name,
        appointments.date, appointments.status
        FROM appointments JOIN patients ON appointments.patient_id = patients.id
        JOIN doctors ON appointments.doctor_id = doctors.id
        ORDER BY appointments.id DESC LIMIT 8"""
    ).fetchall()
    return render_template("reports.html", summary=summary, billing=billing, recent=recent)


@app.route("/delete_doctor", methods=["GET", "POST"])
@login_required
@admin_required
def delete_doctor():
    database = get_db()
    if request.method == "POST":
        doctor_id = request.form.get("doctor_id")
        linked = database.execute(
            "SELECT 1 FROM appointments WHERE doctor_id = ? LIMIT 1", (doctor_id,)
        ).fetchone()
        if linked:
            flash("Doctor cannot be deleted because appointments are linked to this doctor.", "error")
        else:
            result = database.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
            database.commit()
            flash("Doctor deleted." if result.rowcount else "Doctor not found.",
                  "success" if result.rowcount else "error")
    rows = database.execute("SELECT * FROM doctors ORDER BY name").fetchall()
    return render_template("delate_doctors.html", doctors=rows)


@app.route("/delete_doctor/<int:doctor_id>", methods=["POST"])
@login_required
@admin_required
def delete_doctor_link(doctor_id):
    database = get_db()
    linked = database.execute(
        "SELECT 1 FROM appointments WHERE doctor_id = ? LIMIT 1", (doctor_id,)
    ).fetchone()
    if linked:
        flash("Doctor cannot be deleted because appointments are linked to this doctor.", "error")
    else:
        result = database.execute("DELETE FROM doctors WHERE id = ?", (doctor_id,))
        database.commit()
        flash("Doctor deleted." if result.rowcount else "Doctor not found.",
              "success" if result.rowcount else "error")
    return redirect(url_for("delete_doctor"))


@app.route("/logout")
def logout():
    session.clear()
    flash("Logged out successfully.", "success")
    return redirect(url_for("index"))


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=True)
