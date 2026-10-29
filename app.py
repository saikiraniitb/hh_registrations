import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from bson import ObjectId
from pymongo import MongoClient
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title="Hiringhood | Multi-contest MCQ Monitor", page_icon="📊", layout="wide")
IST = ZoneInfo("Asia/Kolkata")
DB_NAME = os.getenv("MONGO_DB", "Marketplace")
DEFAULT_IDS = [
    "6ae0de9ac4a2c5c791cfea9f",  # Data Engineer - Mid
    "6ae0de2aadbc2668e8190525",  # Data Engineer - Junior
    "6ae0dfbfadbc2668e8190529",  # Data Engineer - Senior
]
CONTEST_IDS = [x.strip() for x in os.getenv("MATCHDAY_CONTEST_IDS", ",".join(DEFAULT_IDS)).split(",") if x.strip()]
REFRESH_MS = max(1, int(os.getenv("REFRESH_MINUTES", "25"))) * 60 * 1000


def sid(value):
    return str(value) if value is not None else ""


def mongo_ids(values):
    result = list(values)
    for value in values:
        if isinstance(value, str) and ObjectId.is_valid(value):
            result.append(ObjectId(value))
    return result


def timestamp(value):
    if not isinstance(value, datetime):
        return datetime.min.replace(tzinfo=timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def fmt_date(value):
    return timestamp(value).astimezone(IST).strftime("%d %b %Y %I:%M %p") if isinstance(value, datetime) else ""


def normal_email(value):
    return str(value or "").strip().casefold()


def name_from(profile, user):
    info = profile.get("personal_info") or {}
    return " ".join(str(info.get(k) or "").strip() for k in ("firstName", "middleName", "lastName")).strip() or " ".join(str(user.get(k) or "").strip() for k in ("firstName", "lastName")).strip() or user.get("name") or ""


@st.cache_resource
def get_client(uri):
    return MongoClient(uri, serverSelectionTimeoutMS=12000, readPreference="secondaryPreferred")


@st.cache_data(ttl=60, show_spinner="Reading MongoDB…")
def load_data(_client, ids):
    db = _client[DB_NAME]
    cid_values = mongo_ids(list(ids))
    contests = list(db.contests.find({"contestId": {"$in": cid_values}}, {"contestId": 1, "details.jobDetails.jobTitle": 1}))
    titles = {sid(c.get("contestId")): (c.get("details") or {}).get("jobDetails", {}).get("jobTitle", sid(c.get("contestId"))) for c in contests}
    members = list(db.jobSeekerContests.find({"contestId": {"$in": cid_values}}, {"contestId": 1, "jobSeekerId": 1, "applicationStatus": 1, "byRecruiter": 1, "referedBy": 1, "createdAt": 1}))
    attempts = list(db.mcqAttempts.find({"contestId": {"$in": cid_values}}, {"contestId": 1, "jobseekerId": 1, "recruiterId": 1, "status": 1, "startedAt": 1, "submittedAt": 1, "result.percentageScore": 1}))
    candidate_ids = {sid(x.get("jobSeekerId")) for x in members if x.get("jobSeekerId")}
    candidate_ids.update(sid(x.get("jobseekerId")) for x in attempts if x.get("jobseekerId"))
    users = list(db.users.find({"_id": {"$in": mongo_ids(list(candidate_ids))}}, {"email": 1, "source": 1, "name": 1, "firstName": 1, "lastName": 1}))
    profiles = list(db.jobSeekerProfile.find({"_id": {"$in": mongo_ids(list(candidate_ids))}}, {"personal_info.firstName": 1, "personal_info.middleName": 1, "personal_info.lastName": 1, "personal_info.email": 1, "personal_info.phoneNumber": 1}))
    # One upload may appear multiple times. Choose a candidate/contest-specific record without multiplying totals.
    uploads = list(db.recruiterAddProfiles.find({"contestId": {"$in": cid_values}}, {"contestId": 1, "recruiterId": 1, "jobseekerDetails.jsId": 1, "jobseekerDetails.source": 1, "jobseekerDetails.createdAt": 1}))
    recruiter_ids = {sid(a.get("recruiterId")) for a in attempts if a.get("recruiterId")}
    recruiter_ids.update(sid(u.get("recruiterId")) for u in uploads if u.get("recruiterId"))
    recruiters = list(db.recruiterProfile.find({"_id": {"$in": mongo_ids(list(recruiter_ids))}}, {"basic_details.firstName": 1, "basic_details.middleName": 1, "basic_details.lastName": 1, "additionalData.display_name": 1}))
    recruiter_users = list(db.users.find({"_id": {"$in": mongo_ids(list(recruiter_ids))}}, {"email": 1, "role": 1}))
    bookings = list(db.matchdaySlotBookings.find({}, {"userId": 1, "email": 1, "slotDate": 1, "slotTime": 1, "createdAt": 1}))
    return titles, members, attempts, users, profiles, uploads, recruiters, recruiter_users, bookings


def build_rows(data):
    titles, members, attempts, users, profiles, uploads, recruiters, recruiter_users, bookings = data
    user_map = {sid(u["_id"]): u for u in users}
    profile_map = {sid(p["_id"]): p for p in profiles}
    recruiter_map = {sid(r["_id"]): r for r in recruiters}
    recruiter_user_map = {sid(u["_id"]): u for u in recruiter_users}
    # Preserve contest-specific membership, even if the same candidate joins several contests.
    membership = {}
    for m in members:
        k = (sid(m.get("contestId")), sid(m.get("jobSeekerId")))
        if k[0] and k[1] and (k not in membership or timestamp(m.get("createdAt")) > timestamp(membership[k].get("createdAt"))):
            membership[k] = m
    latest = {}
    for a in attempts:
        k = (sid(a.get("contestId")), sid(a.get("jobseekerId")))
        if not k[0] or not k[1]:
            continue
        old = latest.get(k)
        if not old or timestamp(a.get("submittedAt") or a.get("startedAt")) >= timestamp(old.get("submittedAt") or old.get("startedAt")):
            latest[k] = a
    sources = {}
    for upload in uploads:
        cid = sid(upload.get("contestId"))
        for item in upload.get("jobseekerDetails", []):
            k = (cid, sid(item.get("jsId")))
            if k not in sources or timestamp(item.get("createdAt")) >= timestamp(sources[k][0].get("createdAt")):
                sources[k] = (item, sid(upload.get("recruiterId")))
    member_ids = {jid for _, jid in membership}
    member_emails = {normal_email(user_map.get(jid, {}).get("email") or (profile_map.get(jid, {}).get("personal_info") or {}).get("email")) for jid in member_ids}
    member_emails.discard("")
    # Bookings contain no contest ID. They are candidate-level and may appear for multiple contests.
    booking_map = {}
    for b in bookings:
        bid = sid(b.get("userId"))
        email = normal_email(b.get("email"))
        if bid not in member_ids and email not in member_emails:
            continue
        if bid:
            keys = [bid]
        else:
            keys = [jid for jid in member_ids if normal_email(user_map.get(jid, {}).get("email") or (profile_map.get(jid, {}).get("personal_info") or {}).get("email")) == email]
        for jid in keys:
            old = booking_map.get(jid)
            if old is None or timestamp(b.get("createdAt")) >= timestamp(old.get("createdAt")):
                booking_map[jid] = b
    rows = []
    for cid, jid in sorted(set(membership) | set(latest)):
        m = membership.get((cid, jid), {})
        a = latest.get((cid, jid), {})
        u = user_map.get(jid, {})
        p = profile_map.get(jid, {})
        info = p.get("personal_info") or {}
        upload, upload_rid = sources.get((cid, jid), ({}, ""))
        rid = upload_rid or sid(a.get("recruiterId"))
        r = recruiter_map.get(rid, {})
        details = r.get("basic_details") or {}
        recruiter_name = " ".join(str(details.get(k) or "").strip() for k in ("firstName", "middleName", "lastName")).strip() or (r.get("additionalData") or {}).get("display_name") or ""
        rec_email = recruiter_user_map.get(rid, {}).get("email") or details.get("email") or ""
        if not recruiter_name and rec_email:
            recruiter_name = rec_email.split("@")[0].replace(".", " ").title()
        completed = a.get("status") == "evaluated" and bool(a.get("submittedAt"))
        has_attempt = bool(a)
        booking = booking_map.get(jid) if (cid, jid) in membership else None
        if completed and booking:
            state = "🟢 MCQ + slot booked"
        elif completed:
            state = "🟠 MCQ completed only"
        elif booking:
            state = "🔵 Slot booked, MCQ pending"
        elif a.get("status") == "in_progress":
            state = "🟡 MCQ in progress"
        else:
            state = "⚪ Not completed"
        rows.append({
            "Contest": titles.get(cid, cid), "Contest ID": cid,
            "Name": name_from(p, u),
            "Email": u.get("email") or info.get("email") or "",
            "Phone Number": info.get("phoneNumber") or "",
            "Profile Source": upload.get("source") or u.get("source") or "",
            "Recruiter Name": recruiter_name,
            "Recruiter Email": rec_email,
            "MCQ Given?": "Yes" if has_attempt else "No",
            "MCQ Given For": titles.get(cid, cid) if has_attempt else "",
            "Status": state, "MCQ Status": a.get("status") or "Not started",
            "Score (%)": (a.get("result") or {}).get("percentageScore"),
            "MCQ Started (IST)": fmt_date(a.get("startedAt")),
            "Submitted (IST)": fmt_date(a.get("submittedAt")),
            "Application Status": m.get("applicationStatus") or "",
            "Slot Date": booking.get("slotDate", "") if booking else "",
            "Slot Time": booking.get("slotTime", "") if booking else "",
            "Jobseeker ID": jid,
        })
    return pd.DataFrame(rows)


st.title("Hiringhood · Multi-contest MCQ Monitor")
st.caption("Data Engineer Junior / Mid / Senior · 25-minute auto-refresh while open · read-only")
uri = os.getenv("MONGODB_URI", "")
if not uri:
    try:
        uri = st.secrets.get("MONGODB_URI", "")
    except Exception:
        uri = ""
if not uri:
    st.error("Configure MONGODB_URI as a Streamlit secret or environment variable using a read-only MongoDB user.")
    st.stop()
if not CONTEST_IDS or any(not ObjectId.is_valid(cid) for cid in CONTEST_IDS):
    st.error("MATCHDAY_CONTEST_IDS must be a comma-separated list of valid MongoDB ObjectIds.")
    st.stop()

st_autorefresh(interval=REFRESH_MS, limit=None, key="multi_contest_refresh")
if st.button("↻ Refresh now"):
    st.cache_data.clear()
    st.rerun()

try:
    data = load_data(get_client(uri), tuple(CONTEST_IDS))
    df = build_rows(data)
except Exception as exc:
    st.error("Could not retrieve MongoDB data. Check access, network and collection permissions.")
    st.caption(type(exc).__name__)
    st.stop()

if df.empty:
    st.warning("No contest memberships or MCQ attempts found for the configured contest IDs.")
    st.stop()

all_names = [data[0].get(cid, cid) for cid in CONTEST_IDS]
selected = st.multiselect("Contests", options=all_names, default=all_names)
view = df[df["Contest"].isin(selected)]
st.caption(f"Last fetched {datetime.now(IST).strftime('%d %b %Y %I:%M:%S %p IST')} · MCQ completed means evaluated + submitted, not necessarily passed.")

if not view.empty:
    complete = view["Status"].isin(["🟢 MCQ + slot booked", "🟠 MCQ completed only"])
    booked = view["Status"].isin(["🟢 MCQ + slot booked", "🔵 Slot booked, MCQ pending"])
    metrics = [
        ("Contest candidate rows", len(view)),
        ("MCQ attempted", int((view["MCQ Given?"] == "Yes").sum())),
        ("MCQ completed", int(complete.sum())),
        ("Slots booked", int(booked.sum())),
        ("MCQ + slot", int((view["Status"] == "🟢 MCQ + slot booked").sum())),
    ]
    for column, (label, value) in zip(st.columns(5), metrics):
        column.metric(label, value)
    st.subheader("Contest-wise MCQ summary")
    summary = view.groupby("Contest", sort=False).agg(
        Candidates=("Jobseeker ID", "count"),
        MCQ_Attempted=("MCQ Given?", lambda x: int((x == "Yes").sum())),
        MCQ_Completed=("MCQ Status", lambda x: int((x == "evaluated").sum())),
        Slots_Booked=("Slot Date", lambda x: int(x.fillna("").astype(str).ne("").sum())),
    ).reset_index()
    st.dataframe(summary, hide_index=True, use_container_width=True)
    left, right = st.columns(2)
    with left:
        st.subheader("Candidate progress")
        st.bar_chart(view["Status"].value_counts())
    with right:
        st.subheader("Bookings by slot")
        booked_rows = view[view["Slot Date"].fillna("").astype(str).ne("")]
        if booked_rows.empty:
            st.info("No synced slot bookings for the selected contests.")
        else:
            st.dataframe(booked_rows.groupby(["Slot Date", "Slot Time"]).size().reset_index(name="Contest memberships"), hide_index=True, use_container_width=True)

st.subheader("Candidate-level tracker")
statuses = ["All"] + sorted(view["Status"].dropna().unique().tolist())
status_filter = st.selectbox("Filter by status", statuses)
mcq_filter = st.selectbox("MCQ given", ["All", "Yes", "No"])
search = st.text_input("Search name, email, phone, recruiter or Jobseeker ID")
filtered = view.copy()
if status_filter != "All":
    filtered = filtered[filtered["Status"] == status_filter]
if mcq_filter != "All":
    filtered = filtered[filtered["MCQ Given?"] == mcq_filter]
if search:
    columns = ["Name", "Email", "Phone Number", "Recruiter Name", "Jobseeker ID"]
    filtered = filtered[filtered[columns].fillna("").astype(str).apply(lambda col: col.str.contains(search, case=False, regex=False)).any(axis=1)]
st.dataframe(filtered, hide_index=True, use_container_width=True, height=470)
st.download_button("Download filtered CSV", filtered.to_csv(index=False).encode("utf-8-sig"), file_name=f"hh_multi_contest_mcq_{datetime.now(IST).strftime('%Y%m%d_%H%M')}.csv", mime="text/csv")
st.caption("A candidate may appear once per contest. Slot bookings have no contestId and are attributed via verified contest membership; Zoho-only bookings not synced to matchdaySlotBookings are excluded. Missing profile source/recruiter fields remain blank rather than inferred.")
