import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
from sqlalchemy import create_engine
from datetime import datetime, date
from io import BytesIO
from PIL import Image
import base64
import os

# ----------------------- CONFIG -----------------------
APP_TITLE = "4-Day Live Training Tracker"
PASSCODE = os.getenv("TRACKER_PASSCODE", "")  # Optional: set in Streamlit Secrets
DB_PATH = "sqlite:///tracker.db"

DEFAULT_MACROS = {
    "calories": 2450,
    "protein_g": 190,
    "fat_g": 60,
    "carb_g_rest": 220,
    "carb_g_lift": 280,
    "carb_g_football": 320
}
TDEE_EST = 3000

# Program structure for Mon/Tue/Thu/Fri
PROGRAM = {
    "Monday - Push": [
        ("Incline DB Press", "4x8-10", "25 kg DBs start"),
        ("Flat DB Press", "3x8-10", "22.5 kg DBs start"),
        ("Cable/Pec Deck Fly", "3x12-15", ""),
        ("Seated DB OHP", "3x6-8", "20 kg DBs start"),
        ("Lateral Raise", "4x12-20", ""),
        ("Cable Rope Pressdown", "3x10-12", "15 kg → 20 kg next"),
        ("Ab Wheel (opt.)", "2x8-12", "")
    ],
    "Tuesday - Lower A (Squat)": [
        ("Leg Press (full depth)", "4x8-10", "140 kg start"),
        ("DB RDL", "3x8-10", "25 kg DBs start"),
        ("Bulgarian Split Squat (Smith)", "3x8-10/side", "Bar + 20 kg total"),
        ("Leg Extension", "3x12-15", "50 kg start"),
        ("Standing Calf Raise", "3x15-20", "35–40 kg"),
        ("Hanging Leg Raise", "2x10-12", "")
    ],
    "Thursday - Pull": [
        ("Lat Pulldown (machine)", "4x8-10", "28.5 kg start"),
        ("Chest-Supported DB Row", "4x8-10", "27.5 kg DBs start"),
        ("One-Arm Cable Row", "3x10-12/side", ""),
        ("Rear-Delt Fly", "3x15", ""),
        ("EZ-Bar Curl", "3x8-12", "22.5 kg bar+plates"),
        ("Incline DB Curl", "2x12-15", ""),
        ("Pallof Press", "2x10/side", "")
    ],
    "Friday - Lower B (Hinge)": [
        ("Hip Thrust (Smith)", "4x8-10", "50 kg start"),
        ("Single-Leg RDL (DB)", "3x8-10/side", "18–22.5 kg DBs"),
        ("Leg Curl (machine)", "3x12-15", "40 kg start"),
        ("Front Squat or Leg Press", "3x8-10", ""),
        ("Seated Calf Raise", "3x12-15", "35–40 kg"),
        ("Copenhagen Side Plank", "2x20-30s/side", "")
    ]
}

FOOTBALL = {
    "Thursday Training": {"duration_min": 60, "type": "HIIT/mixed"},
    "Saturday Match": {"duration_min": 30, "type": "HIIT/tempo 30–90 min"}
}

# -------------------- DB SETUP ------------------------
engine = create_engine(DB_PATH)
with engine.connect() as conn:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS workouts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_date TEXT,
        day_name TEXT,
        exercise TEXT,
        sets INTEGER,
        reps INTEGER,
        weight REAL,
        rir REAL,
        notes TEXT
    );
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS body_metrics (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        metric_date TEXT,
        weight_kg REAL,
        waist_cm REAL,
        sleep_h REAL,
        steps INTEGER,
        calories INTEGER
    );
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS photos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        photo_date TEXT,
        caption TEXT,
        image_b64 TEXT
    );
    """)
    conn.execute("""
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY,
        calories INTEGER,
        protein_g INTEGER,
        fat_g INTEGER,
        carb_g_rest INTEGER,
        carb_g_lift INTEGER,
        carb_g_football INTEGER,
        tdee INTEGER
    );
    """)
    # Seed settings if empty
    cur = conn.execute("SELECT COUNT(*) FROM settings").fetchone()[0]
    if cur == 0:
        conn.execute("""
        INSERT INTO settings (id, calories, protein_g, fat_g, carb_g_rest, carb_g_lift, carb_g_football, tdee)
        VALUES (1, :cal, :p, :f, :cr, :cl, :cf, :tdee)
        """, dict(cal=DEFAULT_MACROS["calories"], p=DEFAULT_MACROS["protein_g"],
                  f=DEFAULT_MACROS["fat_g"], cr=DEFAULT_MACROS["carb_g_rest"],
                  cl=DEFAULT_MACROS["carb_g_lift"], cf=DEFAULT_MACROS["carb_g_football"],
                  tdee=TDEE_EST))

# ------------------ UTILS ----------------------------
def load_table(name):
    return pd.read_sql(f"SELECT * FROM {name}", engine)

def write_workout(rows: list[dict]):
    df = pd.DataFrame(rows)
    df.to_sql("workouts", engine, if_exists="append", index=False)

def write_metric(row: dict):
    pd.DataFrame([row]).to_sql("body_metrics", engine, if_exists="append", index=False)

def write_photo(photo_date: str, caption: str, file):
    img = Image.open(file).convert("RGB")
    img.thumbnail((1280, 1280))
    buf = BytesIO()
    img.save(buf, format="JPEG", quality=85)
    b64 = base64.b64encode(buf.getvalue()).decode()
    pd.DataFrame([{"photo_date": photo_date, "caption": caption, "image_b64": b64}]).to_sql(
        "photos", engine, if_exists="append", index=False)

def get_settings():
    s = load_table("settings")
    return s.iloc[0].to_dict() if len(s) else DEFAULT_MACROS | {"tdee": TDEE_EST}

def update_settings(d):
    with engine.begin() as conn:
        conn.execute("""
        UPDATE settings SET calories=:cal, protein_g=:p, fat_g=:f,
        carb_g_rest=:cr, carb_g_lift=:cl, carb_g_football=:cf, tdee=:tdee WHERE id=1
        """, dict(cal=int(d["calories"]), p=int(d["protein_g"]), f=int(d["fat_g"]),
                  cr=int(d["carb_g_rest"]), cl=int(d["carb_g_lift"]),
                  cf=int(d["carb_g_football"]), tdee=int(d["tdee"])))

def e1rm(weight, reps):
    # Brzycki estimate
    if pd.isna(weight) or pd.isna(reps) or reps <= 0:
        return np.nan
    return weight * (36 / (37 - reps))

# ------------------ AUTH (Optional) ------------------
if PASSCODE:
    st.session_state.setdefault("authed", False)
    if not st.session_state["authed"]:
        st.title(APP_TITLE)
        code = st.text_input("Enter passcode", type="password")
        if st.button("Unlock"):
            if code == PASSCODE:
                st.session_state["authed"] = True
                st.experimental_rerun()
            else:
                st.error("Wrong passcode")
        st.stop()

# ------------------ UI NAV ---------------------------
st.set_page_config(page_title=APP_TITLE, page_icon="💪", layout="wide")
st.title(APP_TITLE)

tab = st.sidebar.radio("Navigate", ["Dashboard", "Log Workout", "Body Metrics", "Photos", "Settings", "Data Export/Import"])

# -------------- DASHBOARD ----------------------------
if tab == "Dashboard":
    st.subheader("Overview")
    w = load_table("workouts")
    m = load_table("body_metrics")
    s = get_settings()

    colA, colB, colC, colD = st.columns(4)
    colA.metric("Target Calories", s["calories"])
    colB.metric("Protein (g)", s["protein_g"])
    colC.metric("Fat (g)", s["fat_g"])
    colD.metric("TDEE est.", s["tdee"])

    if not m.empty:
        m["metric_date"] = pd.to_datetime(m["metric_date"])
        m = m.sort_values("metric_date")
        fig_bw = px.line(m, x="metric_date", y="weight_kg", title="Body Weight (kg)")
        fig_waist = px.line(m, x="metric_date", y="waist_cm", title="Waist (cm)")
        st.plotly_chart(fig_bw, use_container_width=True)
        st.plotly_chart(fig_waist, use_container_width=True)
    else:
        st.info("Add body metrics to see charts.")

    st.subheader("Training Volume & e1RM")
    if not w.empty:
        # Volume by day
        w["session_date"] = pd.to_datetime(w["session_date"])
        w["volume"] = w["sets"] * w["reps"] * w["weight"]
        vol = w.groupby([pd.Grouper(key="session_date", freq="W-MON"), "day_name"])["volume"].sum().reset_index()
        fig_vol = px.bar(vol, x="session_date", y="volume", color="day_name", title="Weekly Volume by Session")
        st.plotly_chart(fig_vol, use_container_width=True)

        # e1RM trends for a few key lifts
        key_lifts = ["Incline DB Press", "Leg Press (full depth)", "Hip Thrust (Smith)", "Chest-Supported DB Row"]
        ew = w[w["exercise"].isin(key_lifts)].copy()
        ew["e1rm"] = ew.apply(lambda r: e1rm(r["weight"], r["reps"]), axis=1)
        fig_e1 = px.scatter(ew, x="session_date", y="e1rm", color="exercise", title="Estimated 1RM (selected lifts)", trendline="ols")
        st.plotly_chart(fig_e1, use_container_width=True)
    else:
        st.info("Log workouts to see volume and e1RM charts.")

    st.subheader("Football Schedule")
    st.write("- Thursday: Training (~60 min, evening)")
    st.write("- Saturday: Match (30–90 min)")

# -------------- LOG WORKOUT --------------------------
elif tab == "Log Workout":
    today = st.date_input("Session Date", value=date.today())
    day = st.selectbox("Day / Session", list(PROGRAM.keys()))
    st.caption("Program reference:")
    st.table(pd.DataFrame(PROGRAM[day], columns=["Exercise", "Sets x Reps", "Notes"]))

    st.write("Log your sets")
    entries = []
    ex = st.selectbox("Exercise", [e[0] for e in PROGRAM[day]])
    sets = st.number_input("Sets completed", 1, 10, value=3)
    reps = st.number_input("Reps per set (avg)", 1, 30, value=8)
    weight = st.number_input("Weight (kg) (per DB if applicable)", 0.0, 500.0, value=0.0, step=0.5)
    rir = st.number_input("RIR (reps in reserve)", 0.0, 4.0, value=1.5, step=0.5)
    notes = st.text_input("Notes (PR, tempo, etc.)", "")

    if st.button("Add Entry"):
        entries.append({
            "session_date": str(today),
            "day_name": day,
            "exercise": ex,
            "sets": int(sets),
            "reps": int(reps),
            "weight": float(weight),
            "rir": float(rir),
            "notes": notes
        })
        write_workout(entries)
        st.success("Saved.")

    st.divider()
    st.subheader("Today’s log")
    w = pd.read_sql("SELECT * FROM workouts WHERE session_date = :d ORDER BY id DESC", engine, params={"d": str(today)})
    st.dataframe(w, use_container_width=True)

# -------------- BODY METRICS -------------------------
elif tab == "Body Metrics":
    st.subheader("Add new entry")
    d = st.date_input("Date", value=date.today())
    weight_kg = st.number_input("Body weight (kg)", 0.0, 300.0, 87.6, step=0.1)
    waist_cm = st.number_input("Waist (cm @ navel)", 0.0, 200.0, 93.0, step=0.5)
    sleep = st.number_input("Sleep (hours)", 0.0, 14.0, 7.5, step=0.5)
    steps = st.number_input("Steps", 0, 50000, 9000, step=500)
    calories = st.number_input("Calories (kcal)", 0, 6000, DEFAULT_MACROS["calories"], step=50)

    if st.button("Save metrics"):
        write_metric({
            "metric_date": str(d),
            "weight_kg": float(weight_kg),
            "waist_cm": float(waist_cm),
            "sleep_h": float(sleep),
            "steps": int(steps),
            "calories": int(calories)
        })
        st.success("Saved.")

    st.divider()
    st.subheader("History")
    m = load_table("body_metrics")
    st.dataframe(m.sort_values("metric_date", ascending=False), use_container_width=True)

# -------------- PHOTOS -------------------------------
elif tab == "Photos":
    st.subheader("Upload progress photo")
    pdte = st.date_input("Photo date", value=date.today())
    caption = st.text_input("Caption (e.g., Week 4, 21.1% → 18%)")
    file = st.file_uploader("Choose image", type=["jpg", "jpeg", "png"])
    if st.button("Upload") and file is not None:
        write_photo(str(pdte), caption, file)
        st.success("Uploaded.")

    st.divider()
    st.subheader("Gallery")
    p = load_table("photos")
    if p.empty:
        st.info("No photos yet.")
    else:
        cols = st.columns(3)
        for i, row in p.iterrows():
            img = Image.open(BytesIO(base64.b64decode(row["image_b64"])))
            cols[i % 3].image(img, caption=f'{row["photo_date"]} - {row["caption"]}', use_column_width=True)

# -------------- SETTINGS -----------------------------
elif tab == "Settings":
    st.subheader("Nutrition targets & TDEE")
    s = get_settings()
    c1, c2, c3 = st.columns(3)
    s["calories"] = c1.number_input("Cut Calories", 1200, 5000, int(s["calories"]), step=50)
    s["protein_g"] = c2.number_input("Protein (g)", 80, 300, int(s["protein_g"]), step=5)
    s["fat_g"] = c3.number_input("Fat (g)", 20, 150, int(s["fat_g"]), step=5)
    c4, c5, c6 = st.columns(3)
    s["carb_g_rest"] = c4.number_input("Carbs Rest (g)", 50, 600, int(s["carb_g_rest"]), step=10)
    s["carb_g_lift"] = c5.number_input("Carbs Lift Day (g)", 50, 600, int(s["carb_g_lift"]), step=10)
    s["carb_g_football"] = c6.number_input("Carbs Football Day (g)", 50, 600, int(s["carb_g_football"]), step=10)
    s["tdee"] = st.number_input("TDEE Estimate", 1500, 6000, int(s["tdee"]), step=50)

    if st.button("Save Settings"):
        update_settings(s)
        st.success("Saved.")

    st.info("Tip: On Thursday (football) and Saturday (match), use football carbs target; on Mon/Tue/Fri use lift-day carbs; on rest use rest-day carbs.")

# -------------- DATA EXPORT/IMPORT -------------------
elif tab == "Data Export/Import":
    st.subheader("Export CSVs")
    w = load_table("workouts")
    m = load_table("body_metrics")
    p = load_table("photos")

    def dl(df, name):
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button(f"Download {name}.csv", csv, file_name=f"{name}.csv", mime="text/csv")

    dl(w, "workouts")
    dl(m, "body_metrics")
    dl(p[["photo_date", "caption"]], "photos_meta")

    st.subheader("Import Workouts CSV")
    f = st.file_uploader("Upload CSV (columns: session_date, day_name, exercise, sets, reps, weight, rir, notes)", type=["csv"])
    if f is not None:
        df = pd.read_csv(f)
        df.to_sql("workouts", engine, if_exists="append", index=False)
        st.success(f"Imported {len(df)} rows.")
