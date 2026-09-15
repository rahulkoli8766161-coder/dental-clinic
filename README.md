# Dental Clinic

A Flask and SQLite dental clinic management system with separate patient and admin workflows.

## Features

- Patient registration and login
- Doctor directory and appointment booking
- Patient appointment history and cancellation
- Admin appointment status management
- Billing records and clinic reports
- SQLite database created automatically on first run

## Run locally

```powershell
python -m pip install flask werkzeug
python dental_clinic.py
```

Open `http://127.0.0.1:5000` in a browser.

The default admin login is `admin` / `admin123`. Change these credentials before production use.
