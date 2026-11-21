# Khandwa Tikkad Hotel

Restaurant website and Flask backend for table reservations, a SQLite-backed public menu, and a private staff booking dashboard.

## Run locally

1. Install Python 3.12 or newer.
2. Install dependencies:

   ```powershell
   python -m pip install -r requirements.txt
   ```

3. Configure the staff code and session key before starting the server:

   ```powershell
   $env:STAFF_ACCESS_CODE = "choose-a-private-code-of-at-least-8-characters"
   $env:SECRET_KEY = "choose-a-long-random-secret"
   python app.py
   ```

4. Open `http://localhost:5500`.

The application creates and initializes `hotel.db` on first run. The database is intentionally excluded from Git because it can contain private booking information.

## Render deployment

The included `render.yaml` configures a free Python web service and generated secrets. Its SQLite database is stored at `/tmp/hotel.db` on Render's ephemeral filesystem, so bookings can be lost whenever the service restarts or redeploys. This free configuration is not suitable for durable production bookings. Use a paid Render service with a persistent disk or move to a managed database before relying on booking data.

## Routes

- `/` — restaurant landing page
- `/menu` — menu, loaded from `/api/menu`
- `/staff.html` — staff login; booking data requires an authenticated staff session
- `/api/bookings` — create a reservation
