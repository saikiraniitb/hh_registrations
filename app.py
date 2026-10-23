import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import pandas as pd
import streamlit as st
from pymongo import MongoClient
from streamlit_autorefresh import st_autorefresh

st.set_page_config(page_title='Hiringhood Matchday | Live Monitor',page_icon='📊',layout='wide')
IST = ZoneInfo('Asia/Kolkata')
DB_NAME = os.getenv('MONGO_DB', 'Marketplace')
CONTEST_ID = os.getenv('MATCHDAY_CONTEST_ID','6ad8f9ef121fabbbd2c4cea1')
REFRESH_MS = int(os.getenv('REFRESH_MINUTES','25')) * 60 * 1000

st.title('Hiringhood · Phygital Matchday')
st.caption('24–25 October 2026 • MCQ completion & slot booking • Auto-refresh every 25 minutes while this page is open')

uri = os.getenv('MONGODB_URI', '')
if not uri:
    try:
        uri = st.secrets.get('MONGODB_URI', '')
    except Exception:
        uri = ''
if not uri:
    st.error('MongoDB connection missing. Set MONGODB_URI as an environment variable or in Streamlit secrets. Use a read-only database user.')
    st.stop()

st_autorefresh(interval=REFRESH_MS, limit=None, key='matchday_refresh')
if st.button('↻ Refresh now'):
    st.cache_data.clear()
    st.rerun()

@st.cache_resource
# A single pooled client is reused; never display credentials.
def get_client(mongo_uri):
    return MongoClient(mongo_uri, serverSelectionTimeoutMS=12000, readPreference='secondaryPreferred')

@st.cache_data(ttl=60, show_spinner='Fetching current Matchday records…')
def load_data(_client, contest_id):
    from bson import ObjectId
    db = _client[DB_NAME]
    cid = ObjectId(contest_id)
    attempts = list(db.mcqAttempts.find({'contestId':cid}, {'jobseekerId':1,'status':1,'submittedAt':1,'result.percentageScore':1,'startedAt':1,'_id':1}))
    # Bookings do not carry contestId, so match them to this contest through the user ID/email.
    bookings = list(db.matchdaySlotBookings.find({}, {'userId':1,'email':1,'slotDate':1,'slotTime':1,'createdAt':1}))
    relevant_ids={a.get('jobseekerId') for a in attempts if a.get('jobseekerId')}
    relevant_ids.update(b.get('userId') for b in bookings if b.get('userId'))
    users=list(db.users.find({'_id':{'$in':list(relevant_ids)}},{'email':1,'name':1,'firstName':1,'lastName':1})) if relevant_ids else []
    user_by_id={str(u['_id']):u for u in users}
    user_by_email={str(u.get('email','')).casefold().strip():u for u in users if u.get('email')}
    # Only include bookings for members of the current contest; joining solely on an email without contest validation is not sufficient.
    contest_members = {str(x['jobSeekerId']) for x in db.jobSeekerContests.find({'contestId':cid},{'jobSeekerId':1}) if x.get('jobSeekerId')}
    member_emails = {str(user_by_id[x].get('email','')).casefold().strip() for x in contest_members if x in user_by_id}
    # If booking user isn't in attempts list, load the user separately for contest membership check.
    extra_member_ids = [ObjectId(x) for x in contest_members if x not in user_by_id]
    if extra_member_ids:
        for u in db.users.find({'_id':{'$in':extra_member_ids}},{'email':1,'name':1,'firstName':1,'lastName':1}):
            user_by_id[str(u['_id'])] = u
            if u.get('email'):
                user_by_email[str(u['email']).casefold().strip()]=u
    member_emails={str(user_by_id[x].get('email','')).casefold().strip() for x in contest_members if x in user_by_id}
    return attempts,bookings,user_by_id,member_emails,contest_members

def fmt_date(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:value=value.replace(tzinfo=timezone.utc)
        return value.astimezone(IST).strftime('%d %b %Y %I:%M %p')
    return ''

try:
    attempts, bookings, user_by_id, member_emails, contest_members = load_data(get_client(uri), CONTEST_ID)
except Exception as exc:
    st.error('Could not read MongoDB. Check network access, credentials and read permissions.')
    st.caption(type(exc).__name__)
    st.stop()

by_id={}
for a in attempts:
    if not a.get('jobseekerId'):continue
    key=str(a['jobseekerId'])
    prev=by_id.get(key)
    stamp=a.get('submittedAt') or a.get('startedAt') or datetime.min
    prev_stamp=(prev.get('submittedAt') or prev.get('startedAt') or datetime.min) if prev else datetime.min
    if prev is None or stamp >= prev_stamp:by_id[key]=a

valid_bookings={}
for b in bookings:
    b_id=str(b.get('userId') or '')
    email=str(b.get('email') or user_by_id.get(b_id,{}).get('email') or '').casefold().strip()
    if b_id not in contest_members and email not in member_emails:continue
    if not email:continue
    earlier=valid_bookings.get(email)
    if earlier is None or (b.get('createdAt') or datetime.min)>(earlier.get('createdAt') or datetime.min):valid_bookings[email]=b

rows=[]
for jsid in sorted(set(by_id)|contest_members):
    a=by_id.get(jsid)
    u=user_by_id.get(jsid,{})
    email=str(u.get('email','')).casefold().strip()
    booking=valid_bookings.get(email)
    # Completed means evaluated and submitted; it DOES NOT imply passed any cutoff.
    completed=bool(a and a.get('status')=='evaluated' and a.get('submittedAt'))
    if completed and booking: status='🟢 MCQ + slot booked'
    elif completed: status='🟠 MCQ completed only'
    elif booking: status='🔵 Slot booked, MCQ pending'
    elif a and a.get('status')=='in_progress': status='🟡 MCQ in progress'
    else:status='⚪ Not completed'
    rows.append({'Email':email,'Name':(' '.join(filter(None,[u.get('firstName'),u.get('lastName')])) or u.get('name') or ''),
                 'Status':status,'MCQ Status':a.get('status','Not started') if a else 'Not started',
                 'Score (%)':a.get('result',{}).get('percentageScore') if a else None,
                 'Submitted (IST)':fmt_date(a.get('submittedAt')) if a else '',
                 'Slot Date':booking.get('slotDate','') if booking else '',
                 'Slot Time':booking.get('slotTime','') if booking else '',
                 'Jobseeker ID':jsid})
# Aggregate all attempts, not just one selected latest attempt.
df=pd.DataFrame(rows)
if df.empty:
    st.warning('No candidates matched the current contest in jobSeekerContests. Check MATCHDAY_CONTEST_ID and collection mappings.')
    st.stop()
completed_mask=df['Status'].isin(['🟢 MCQ + slot booked','🟠 MCQ completed only'])
booked_mask=df['Status'].isin(['🟢 MCQ + slot booked','🔵 Slot booked, MCQ pending'])
mcq_and_booked=(df['Status']=='🟢 MCQ + slot booked').sum()
mcq_only=(df['Status']=='🟠 MCQ completed only').sum()
col=st.columns(5)
for c,label,val in zip(col,['Contest candidates','MCQ completed','Slots booked','MCQ + slot','MCQ only'],[len(df),int(completed_mask.sum()),int(booked_mask.sum()),int(mcq_and_booked),int(mcq_only)]):
    c.metric(label,val)
st.caption(f'Data fetched at {datetime.now(IST).strftime("%d %b %Y %I:%M:%S %p IST")} • Completed = evaluated/submitted, not necessarily qualified')

left,right=st.columns([1.25,1])
with left:
    st.subheader('Candidate progress')
    display_counts=df['Status'].value_counts().sort_index()
    st.bar_chart(display_counts)
with right:
    st.subheader('Bookings by date / slot')
    booked=df.loc[booked_mask,['Slot Date','Slot Time']]
    if len(booked):st.dataframe(booked.groupby(['Slot Date','Slot Time']).size().reset_index(name='Booked'),hide_index=True,use_container_width=True)
    else:st.info('No bookings for this contest yet.')

st.subheader('Candidate-level tracker')
statuses=['All']+sorted(df['Status'].unique().tolist())
chosen=st.selectbox('Filter by status',statuses)
search=st.text_input('Search by email, name or Jobseeker ID')
view=df if chosen=='All' else df[df['Status']==chosen]
if search:view=view[view[['Email','Name','Jobseeker ID']].fillna('').astype(str).apply(lambda c:c.str.contains(search,case=False,regex=False)).any(axis=1)]
st.dataframe(view,hide_index=True,use_container_width=True,height=460)
st.download_button('Download current status CSV',df.to_csv(index=False).encode('utf-8-sig'),file_name=f'hh_matchday_status_{datetime.now(IST).strftime("%Y%m%d_%H%M")}.csv',mime='text/csv')
st.caption('Read-only dashboard. Slot records are joined to contest members and MCQ attempts using user ID/email. Reconcile externally booked Zoho slots separately if they are not synced into matchdaySlotBookings.')
