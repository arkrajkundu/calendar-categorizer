import streamlit as st
import datetime
import pickle
import os
import json
import google.generativeai as genai
import pandas as pd
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# =================== CONFIG ===================

web = st.secrets["client_secret"]["web"]

client_secret_clean = {
    "installed": {
        "client_id": web["client_id"],
        "project_id": web["project_id"],
        "auth_uri": web["auth_uri"],
        "token_uri": web["token_uri"],
        "auth_provider_x509_cert_url": web["auth_provider_x509_cert_url"],
        "client_secret": web["client_secret"],
        "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob"],
    }
}

SCOPES = ['https://www.googleapis.com/auth/calendar']
GEMINI_API_KEY = "AIzaSyA1bVAA7lBlc2Zs350--ZZ_FcTuuEdw2X4"  # Replace if needed
MODEL_NAME = "models/gemini-1.5-pro-latest"

CATEGORIES = {
    "1": "Client",
    "2": "Team",
    "5": "One-on-One",
    "6": "Personal",
    "11": "Other"
}

genai.configure(api_key=GEMINI_API_KEY)

# =================== AUTH ===================

def authenticate_google_calendar_manual():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(
                client_secret_clean,
                SCOPES,
                redirect_uri="urn:ietf:wg:oauth:2.0:oob"
            )
            auth_url, _ = flow.authorization_url(prompt='consent')
            st.info("🔗 Please open the following link, sign in, and paste the code below:")
            st.code(auth_url, language="markdown")
            auth_code = st.text_input("🔑 Paste the authorization code here and press Enter:")
            if auth_code:
                try:
                    flow.fetch_token(code=auth_code)
                    creds = flow.credentials
                    with open('token.pickle', 'wb') as token:
                        pickle.dump(creds, token)
                except Exception as e:
                    st.error(f"Auth failed: {e}")
                    return None
            else:
                st.stop()

    return build('calendar', 'v3', credentials=creds)

# =================== GEMINI ===================

def categorize_with_gemini(title, description):
    prompt = f"""
You are a helpful assistant that categorizes meetings based on the title and description.
Return one of these categories:
- Client
- Team
- One-on-One
- Personal
- Other

Only return the category name.

Examples:
Title: "Weekly team sync" → Team  
Title: "Lunch with Alex" → Personal  
Title: "Performance review with manager" → One-on-One  
Title: "Demo for ACME Corp" → Client  

Now categorize:
Title: {title}
Description: {description}
"""
    try:
        model = genai.GenerativeModel(MODEL_NAME)
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        st.error(f"❌ Gemini API error: {e}")
        return "Other"

def category_to_color_id(category):
    for color_id, name in CATEGORIES.items():
        if name.lower() == category.lower():
            return color_id
    return "11"

# =================== MAIN ===================

def main():
    st.set_page_config(page_title="Calendar Categorizer", page_icon="📅")
    st.title("📅 Calendar Categorizer")

    start_date = st.date_input("Start Date", datetime.date.today())
    end_date = st.date_input("End Date", datetime.date.today() + datetime.timedelta(days=7))

    if start_date > end_date:
        st.error("🚫 Start date must be before end date.")
        return

    if st.button("🔍 Fetch and Categorize Events"):
        with st.spinner("🔐 Authenticating..."):
            service = authenticate_google_calendar_manual()
            if not service:
                return

        start_iso = datetime.datetime.combine(start_date, datetime.time.min).isoformat() + 'Z'
        end_iso = datetime.datetime.combine(end_date, datetime.time.max).isoformat() + 'Z'

        with st.spinner("📅 Fetching events..."):
            events_result = service.events().list(
                calendarId='primary',
                timeMin=start_iso,
                timeMax=end_iso,
                singleEvents=True,
                orderBy='startTime'
            ).execute()
            events = events_result.get('items', [])

        if not events:
            st.warning("No events found.")
            return

        output_data = []
        skipped_working_location_count = 0

        with st.spinner("🧠 Categorizing..."):
            for event in events:
                title = event.get('summary', '').strip()
                description = event.get('description', '').strip()
                event_id = event['id']
                is_working_location = event.get('eventType') == 'workingLocation'

                category = categorize_with_gemini(title, description)
                color_id = category_to_color_id(category)

                output_data.append({
                    "Title": title,
                    "Description": description,
                    "Start": event['start'].get('dateTime', event['start'].get('date')),
                    "End": event['end'].get('dateTime', event['end'].get('date')),
                    "Category": category,
                    "Skipped Color Update": "Yes" if is_working_location else "No"
                })

                if is_working_location:
                    skipped_working_location_count += 1
                    continue

                try:
                    service.events().patch(calendarId='primary', eventId=event_id, body={"colorId": color_id}).execute()
                except Exception:
                    pass

        df = pd.DataFrame(output_data)
        st.success("✅ Events categorized successfully!")
        st.dataframe(df)

        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button("📥 Download as CSV", data=csv, file_name="categorized_events.csv", mime='text/csv')

        if skipped_working_location_count > 0:
            st.info(f"⏩ Skipped {skipped_working_location_count} working location event(s).")

if __name__ == "__main__":
    main()
