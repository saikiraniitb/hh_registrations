# Hiringhood Phygital Matchday — MongoDB live dashboard

Tracks the October 24–25, 2026 Matchday in production MongoDB. Reads `Marketplace.mcqAttempts`, `Marketplace.matchdaySlotBookings`, `Marketplace.jobSeekerContests`, and `Marketplace.users` only. No database writes.

## Setup

Use a **read-only** MongoDB Atlas database user and IP allowlist/VPN access. **Do not commit the connection URI or share it in chat.**

```bash
cd hh_matchday_live_dashboard
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export MONGODB_URI='mongodb+srv://<read-only-user>:<url-encoded-password>@<your-cluster>/?retryWrites=false'
streamlit run app.py
```

Open the URL printed by Streamlit (usually `http://localhost:8501`). It auto-refreshes **every 25 minutes while a viewer keeps the page open**. Use the **Refresh now** button at any time.

Environment overrides: `MONGO_DB=Marketplace`, `MATCHDAY_CONTEST_ID=6ad8f9ef121fabbbd2c4cea1`, `REFRESH_MINUTES=25`.

## Important definitions

- **MCQ completed:** `status=evaluated` and `submittedAt` is present. This is not a pass/fail decision.
- **Slot booked:** recorded in `matchdaySlotBookings`, associated with a jobseeker in the selected contest. If your Zoho Bookings slots aren't synced here, they won't show.
- **MCQ + slot booked:** both facts verified for that contest's candidate.
- The dashboard is a live view of MongoDB, not a hosted service. Hosting it 24/7 requires your own Streamlit/cloud/VPS process and network access. Do not expose candidate PII publicly; deploy behind SSO/private access.
