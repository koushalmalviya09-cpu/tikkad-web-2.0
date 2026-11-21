# Khandwa Tikkad Hotel

Restaurant website and Flask backend for table reservations, Razorpay-paid dine-in and pickup orders, a SQLite-backed public menu, and a private staff dashboard.

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

## Enable online ordering

Create Razorpay API keys in the Razorpay Dashboard (use test keys while testing). Configure these server environment variables before starting the app:

```powershell
$env:RAZORPAY_KEY_ID = "your-key-id"
$env:RAZORPAY_KEY_SECRET = "your-key-secret"
```

The secret belongs only on the server. Never add Razorpay secrets to HTML, JavaScript, or GitHub. Without both values, customers can browse the menu but checkout stays disabled.

For production, configure a Razorpay webhook for `payment.captured` at `/api/payments/razorpay/webhook`, set its signing secret as `RAZORPAY_WEBHOOK_SECRET`, and use live keys only after testing a complete payment. Staff can track paid orders and update their preparation status at `/staff.html`. Refunds must be processed in the Razorpay Dashboard.

## Render deployment

The included `render.yaml` configures a free Python web service and generated secrets. Its SQLite database is stored at `/tmp/hotel.db` on Render's ephemeral filesystem, so bookings can be lost whenever the service restarts or redeploys. This free configuration is not suitable for durable production bookings. Use a paid Render service with a persistent disk or move to a managed database before relying on booking data.

To enable checkout on Render, add `RAZORPAY_KEY_ID` and `RAZORPAY_KEY_SECRET` under the service's Environment settings, then redeploy. Add `RAZORPAY_WEBHOOK_SECRET` after creating the webhook. Do not send these secret values in chat or commit them to the repository.

The current free Render configuration stores SQLite at `/tmp/hotel.db`. The app intentionally blocks live Razorpay keys on that temporary path so a restart cannot silently discard paid orders. Razorpay test keys can be used for checkout testing; switch to live keys only after moving orders to persistent storage.

## Routes

- `/` — restaurant landing page
- `/menu` — menu, loaded from `/api/menu`
- `/staff.html` — staff login; booking and order data require an authenticated staff session
- `/api/bookings` — create a reservation
- `/api/orders` — create a payment order using server-calculated menu prices
- `/api/payments/razorpay/webhook` — verify Razorpay captured-payment events
