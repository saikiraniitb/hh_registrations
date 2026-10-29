# Hiringhood Multi-Contest MCQ Dashboard

Read-only Streamlit dashboard for three Data Engineer contests:

| Role | Contest ID |
| --- | --- |
| Junior Level | `6ae0de2aadbc2668e8190525` |
| Mid Level | `6ae0de9ac4a2c5c791cfea9f` |
| Senior Level | `6ae0dfbfadbc2668e8190529` |

The app reads `Marketplace.jobSeekerContests`, `mcqAttempts`, `users`, `jobSeekerProfile`, `recruiterAddProfiles`, `recruiterProfile`, `contests`, and `matchdaySlotBookings`. It never writes to MongoDB.

## Run

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export MONGODB_URI='mongodb+srv://<read-only-user>:<url-encoded-password>@<cluster>/?retryWrites=false'
streamlit run app.py
```

For Streamlit Community Cloud, keep the **Main file path** set to `app.py`, and configure `MONGODB_URI` privately in the app's Secrets settings.

Optional environment variables:

- `MONGO_DB`: default `Marketplace`
- `MATCHDAY_CONTEST_IDS`: comma-separated list of contest IDs shown above
- `REFRESH_MINUTES`: default `25`

## Dashboard

The dashboard includes a contest multi-select, overall metrics, per-contest summary, status/MCQ filters, search, and filtered CSV export.

Candidate rows contain contest/contest ID, name, email, phone, profile source, recruiter name/email, MCQ given, specific MCQ contest, MCQ status, score, start/submission timestamps, application status and slot details.

**Counting:** each distinct (contest ID, jobseeker ID) is one candidate row. Candidates in multiple contests appear once per contest. Upload records are joined only to enrich source and recruiter details, not to inflate contest counts. Repeated attempts are reduced to the most recent attempt for each contest/candidate.

**Completed** means `status=evaluated` with a `submittedAt` timestamp, not a pass/fail threshold. **MCQ given** means an MCQ attempt document exists, including in-progress attempts.

**Profile source** is taken from the matching `recruiterAddProfiles.jobseekerDetails.source` when available, otherwise `users.source`. **Recruiter** is the uploader for the contest when available, otherwise `mcqAttempts.recruiterId`. Missing values stay blank.

**Bookings:** `matchdaySlotBookings` has no contest ID; booking data is mapped to candidate membership and may therefore display for multiple contests for a candidate. Externally booked Zoho slots are not included unless synchronized to this collection.

**Security:** use a MongoDB read-only account, restricted database/network access, and Streamlit SSO/private deployment. Candidate personal information should not be publicly exposed. Never commit credentials or `.streamlit/secrets.toml`.
