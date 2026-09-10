import os
import json
import hashlib
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from bs4 import BeautifulSoup

# =========================
# TELEGRAM
# =========================

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": False
        },
        timeout=20
    )

    response.raise_for_status()


# =========================
# YOUR JOB PREFERENCES
# =========================

LOCATIONS = [
    "pune",
    "mumbai",
    "bangalore",
    "bengaluru",
    "hyderabad"
]

EMBEDDED_KEYWORDS = [
    "embedded",
    "embedded systems",
    "embedded system",
    "embedded c",
    "firmware",
    "microcontroller",
    "microcontroller",
    "mcu",
    "stm32",
    "arm",
    "rtos",
    "iot",
    "electronics",
    "hardware",
    "embedded software",
    "embedded engineer",
    "firmware engineer"
]

FRESHER_KEYWORDS = [
    "fresher",
    "freshers",
    "0 year",
    "0 years",
    "entry level",
    "entry-level",
    "graduate",
    "trainee",
    "intern"
]


# =========================
# RSS / PUBLIC FEEDS
# =========================

RSS_FEEDS = [
    # Google News searches for newly indexed public job postings
    "https://news.google.com/rss/search?q=embedded+jobs+Pune+fresher&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=embedded+jobs+Mumbai+fresher&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=embedded+jobs+Bangalore+fresher&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=embedded+jobs+Hyderabad+fresher&hl=en-IN&gl=IN&ceid=IN:en",

    "https://news.google.com/rss/search?q=firmware+engineer+India+fresher&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=embedded+C+engineer+India+fresher&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=IoT+engineer+India+fresher&hl=en-IN&gl=IN&ceid=IN:en"
]


# =========================
# DUPLICATE DATABASE
# =========================

DB_FILE = Path("seen_jobs.json")

def load_seen():
    if not DB_FILE.exists():
        return set()

    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except Exception:
        return set()


def save_seen(seen):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)


def job_id(title, link):
    value = title + "|" + link
    return hashlib.sha256(value.encode()).hexdigest()


# =========================
# FILTER
# =========================

def is_relevant(title, description):
    text = (title + " " + description).lower()

    embedded_match = any(
        keyword in text
        for keyword in EMBEDDED_KEYWORDS
    )

    location_match = any(
        location in text
        for location in LOCATIONS
    )

    fresher_match = any(
        keyword in text
        for keyword in FRESHER_KEYWORDS
    )

    return embedded_match and location_match and fresher_match


# =========================
# READ RSS
# =========================

def read_feed(feed_url):
    jobs = []

    try:
        response = requests.get(
            feed_url,
            headers={
                "User-Agent": "Mozilla/5.0"
            },
            timeout=30
        )

        response.raise_for_status()

        root = ET.fromstring(response.content)

        for item in root.findall(".//item"):

            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            description = item.findtext("description") or ""
            pub_date = item.findtext("pubDate") or ""

            # Remove HTML from description
            description = BeautifulSoup(
                description,
                "html.parser"
            ).get_text(" ", strip=True)

            jobs.append({
                "title": title.strip(),
                "link": link.strip(),
                "description": description.strip(),
                "date": pub_date.strip()
            })

    except Exception as e:
        print(f"Feed error: {feed_url}")
        print(e)

    return jobs


# =========================
# MAIN
# =========================

def main():

    print("===================================")
    print("      EMBEDDED JOB RADAR")
    print("===================================")

    seen = load_seen()
    new_jobs = []

    for feed in RSS_FEEDS:

        print(f"Checking: {feed}")

        jobs = read_feed(feed)

        for job in jobs:

            title = job["title"]
            link = job["link"]
            description = job["description"]

            if not title or not link:
                continue

            if not is_relevant(title, description):
                continue

            identifier = job_id(title, link)

            if identifier in seen:
                continue

            seen.add(identifier)
            new_jobs.append(job)

    # Save database
    save_seen(seen)

    print(f"New matching jobs: {len(new_jobs)}")

    # Send alerts
    for job in new_jobs:

        message = (
            "🚨 NEW EMBEDDED JOB\n\n"
            f"💼 {job['title']}\n\n"
            f"📍 Search result matched your location criteria\n"
            f"🕐 {job['date']}\n\n"
            f"🔗 Apply / View:\n{job['link']}\n\n"
            "🎯 Fresher + Embedded related"
        )

        try:
            send_telegram(message)
            print("Telegram alert sent.")

        except Exception as e:
            print("Telegram error:", e)


if __name__ == "__main__":
    main()
