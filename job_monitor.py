
import os
import json
import hashlib
import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from ats_sources import fetch_ats_jobs

# ============================================================
# EMBEDDED JOB RADAR — MULTI SOURCE V1
# ============================================================

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

DB_FILE = Path("seen_jobs.json")
COMPANIES_FILE = Path("companies.txt")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EmbeddedJobRadar/1.0)"
}

# ============================================================
# YOUR PREFERENCES
# ============================================================

LOCATIONS = [
    "pune",
    "pimpri",
    "mumbai",
    "bangalore",
    "bengaluru",
    "hyderabad",
]

EMBEDDED_KEYWORDS = [
    "embedded",
    "embedded systems",
    "embedded system",
    "embedded c",
    "embedded software",
    "firmware",
    "firmware engineer",
    "microcontroller",
    "microcontrollers",
    "mcu",
    "stm32",
    "arm cortex",
    "rtos",
    "freeRTOS",
    "iot",
    "internet of things",
    "electronics",
    "hardware",
    "board bring-up",
    "device driver",
    "device drivers",
    "bare metal",
    "bootloader",
    "uart",
    "spi",
    "i2c",
    "can protocol",
    "can bus",
]

FRESHER_KEYWORDS = [
    "fresher",
    "freshers",
    "fresh graduate",
    "recent graduate",
    "entry level",
    "entry-level",
    "graduate",
    "trainee",
    "intern",
    "internship",
    "junior",
    "0 year",
    "0 years",
    "0-1 year",
    "0-2 years",
    "0 to 1 year",
    "0 to 2 years",
    "1 year",
    "1 years",
]

# Clearly experienced/senior roles should not normally reach Telegram.
EXPERIENCED_KEYWORDS = [
    "senior",
    "sr.",
    "sr ",
    "lead engineer",
    "technical lead",
    "principal engineer",
    "staff engineer",
    "architect",
    "engineering manager",
    "project manager",
    "director",
    "head of",
    "5+ years",
    "6+ years",
    "7+ years",
    "8+ years",
    "10+ years",
]

# ============================================================
# PUBLIC RSS SEARCH SOURCES
# ============================================================

RSS_FEEDS = [
    # Google News / public indexed job discovery
    "https://news.google.com/rss/search?q=embedded+jobs+Pune+fresher&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=embedded+jobs+Mumbai+fresher&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=embedded+jobs+Bangalore+fresher&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=embedded+jobs+Hyderabad+fresher&hl=en-IN&gl=IN&ceid=IN:en",

    "https://news.google.com/rss/search?q=firmware+engineer+India+fresher&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=embedded+C+engineer+India+fresher&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=IoT+engineer+India+fresher&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=electronics+engineer+India+fresher&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=STM32+jobs+India+fresher&hl=en-IN&gl=IN&ceid=IN:en",
    "https://news.google.com/rss/search?q=RTOS+embedded+India+fresher&hl=en-IN&gl=IN&ceid=IN:en",
]

# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"

    response = requests.post(
        url,
        data={
            "chat_id": CHAT_ID,
            "text": message,
            "disable_web_page_preview": False,
        },
        timeout=20,
    )

    response.raise_for_status()


# ============================================================
# DATABASE
# ============================================================

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
        json.dump(sorted(list(seen)), f, indent=2)


def job_id(title, link):
    value = title.strip().lower() + "|" + link.strip()
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ============================================================
# HELPERS
# ============================================================

def clean_html(text):
    return BeautifulSoup(
        text or "",
        "html.parser"
    ).get_text(" ", strip=True)


def get_domain(url):
    try:
        return urlparse(url).netloc.lower().replace("www.", "")
    except Exception:
        return ""


def find_location(text):
    text = text.lower()

    for location in LOCATIONS:
        if location in text:
            return location.title()

    return None


def embedded_match(text):
    text = text.lower()

    matches = [
        keyword
        for keyword in EMBEDDED_KEYWORDS
        if keyword.lower() in text
    ]

    return matches


def fresher_status(text):
    text = text.lower()

    if any(
        keyword.lower() in text
        for keyword in EXPERIENCED_KEYWORDS
    ):
        return False, "Experienced/Senior"

    matches = [
        keyword
        for keyword in FRESHER_KEYWORDS
        if keyword.lower() in text
    ]

    if matches:
        return True, matches[0]

    # If experience is not mentioned, keep the job for review
    # rather than losing potentially useful fresher positions.
    return True, "Experience not clearly stated"


def is_relevant(title, description):
    text = f"{title} {description}".lower()

    embedded = embedded_match(text)

    if not embedded:
        return False, None, None, []

    location = find_location(text)

    if not location:
        return False, None, None, embedded

    fresher_ok, fresher_reason = fresher_status(text)

    if not fresher_ok:
        return False, location, fresher_reason, embedded

    return True, location, fresher_reason, embedded


# ============================================================
# GOOGLE / RSS READER
# ============================================================

def read_feed(feed_url):
    jobs = []

    try:
        response = requests.get(
            feed_url,
            headers=HEADERS,
            timeout=30,
        )

        response.raise_for_status()

        root = ET.fromstring(response.content)

        for item in root.findall(".//item"):

            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            description = item.findtext("description") or ""
            pub_date = item.findtext("pubDate") or ""

            description = clean_html(description)

            if title and link:
                jobs.append({
                    "title": title.strip(),
                    "link": link.strip(),
                    "description": description.strip(),
                    "date": pub_date.strip(),
                    "source": "Google News/public search",
                })

    except Exception as e:
        print(f"Feed error: {feed_url}")
        print(e)

    return jobs


# ============================================================
# COMPANY LIST
# ============================================================

def load_companies():
    if not COMPANIES_FILE.exists():
        print("companies.txt not found.")
        return []

    companies = []

    with open(COMPANIES_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            companies.append(line)

    return companies


# ============================================================
# PUBLIC ATS DETECTION
# ============================================================

ATS_DOMAINS = [
    "greenhouse.io",
    "lever.co",
    "ashbyhq.com",
    "myworkdayjobs.com",
    "smartrecruiters.com",
    "recruitee.com",
    "breezy.hr",
    "teamtailor.com",
    "personio.com",
    "bamboohr.com",
    "workable.com",
    "rippling.com",
]


def discover_career_links(domain):
    links = set()

    possible_urls = [
        f"https://{domain}",
        f"https://www.{domain}",
    ]

    for url in possible_urls:

        try:
            response = requests.get(
                url,
                headers=HEADERS,
                timeout=20,
                allow_redirects=True,
            )

            response.raise_for_status()

            soup = BeautifulSoup(
                response.text,
                "html.parser"
            )

            for a in soup.find_all("a", href=True):

                href = a.get("href", "").strip()
                text = a.get_text(" ", strip=True).lower()

                combined = f"{text} {href.lower()}"

                if any(
                    word in combined
                    for word in [
                        "career",
                        "careers",
                        "jobs",
                        "job-opportunities",
                        "work-with-us",
                        "join-us",
                        "vacancies",
                    ]
                ):
                    links.add(
                        requests.compat.urljoin(
                            response.url,
                            href
                        )
                    )

                if any(
                    ats in href.lower()
                    for ats in ATS_DOMAINS
                ):
                    links.add(href)

        except Exception as e:
            print(f"Company discovery error: {domain}")
            print(e)

    return list(links)


# ============================================================
# GENERIC ATS PAGE READER
# ============================================================

def read_public_career_page(url, company_domain):
    jobs = []

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=30,
            allow_redirects=True,
        )

        response.raise_for_status()

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        page_text = soup.get_text(
            " ",
            strip=True
        )

        # This is intentionally conservative.
        # It does not bypass CAPTCHA/login/anti-bot systems.
        #
        # We use the page as a discovery source and extract
        # obvious job links.

        for a in soup.find_all("a", href=True):

            title = a.get_text(
                " ",
                strip=True
            )

            href = requests.compat.urljoin(
                response.url,
                a["href"]
            )

            if not title or len(title) < 4:
                continue

            combined = title + " " + page_text[:5000]

            if not embedded_match(combined):
                continue

            jobs.append({
                "title": title,
                "link": href,
                "description": page_text[:3000],
                "date": "",
                "source": f"Company career page ({company_domain})",
            })

    except Exception as e:
        print(f"Career page error: {url}")
        print(e)

    return jobs


# ============================================================
# MAIN
# ============================================================

def main():

    print("==========================================")
    print("       EMBEDDED JOB RADAR — V1")
    print("==========================================")

    seen = load_seen()
    new_jobs = []

    # --------------------------------------------------------
    # SOURCE 1 — PUBLIC RSS / SEARCH
    # --------------------------------------------------------

    print("\n[1] Checking public RSS/search sources...")

    for feed in RSS_FEEDS:

        print(f"Checking: {feed}")

        jobs = read_feed(feed)

        for job in jobs:

            relevant, location, fresher, skills = is_relevant(
                job["title"],
                job["description"]
            )

            if not relevant:
                continue

            identifier = job_id(
                job["title"],
                job["link"]
            )

            if identifier in seen:
                continue

            seen.add(identifier)

            job["location"] = location
            job["fresher"] = fresher
            job["skills"] = skills

            new_jobs.append(job)

    # --------------------------------------------------------
    # SOURCE 2 — COMPANY CAREER DISCOVERY
    # --------------------------------------------------------

    print("\n[2] Checking company career pages...")

    companies = load_companies()

    for domain in companies:

        print(f"Discovering: {domain}")

        career_links = discover_career_links(domain)

        for career_url in career_links:

            jobs = read_public_career_page(
                career_url,
                domain
            )

            for job in jobs:

                relevant, location, fresher, skills = is_relevant(
                    job["title"],
                    job["description"]
                )

                if not relevant:
                    continue

                identifier = job_id(
                    job["title"],
                    job["link"]
                )

                if identifier in seen:
                    continue

                seen.add(identifier)

                job["location"] = location
                job["fresher"] = fresher
                job["skills"] = skills

                new_jobs.append(job)

    # --------------------------------------------------------
    # SAVE
    # --------------------------------------------------------

    save_seen(seen)

    print("\n==========================================")
    print(f"NEW MATCHING JOBS: {len(new_jobs)}")
    print("==========================================")

    # --------------------------------------------------------
    # TELEGRAM
    # --------------------------------------------------------

    for job in new_jobs:

        skills = ", ".join(
            job.get("skills", [])[:8]
        )

        message = (
            "🚨 NEW EMBEDDED JOB\n\n"
            f"💼 {job['title']}\n\n"
            f"🏢 Source: {job['source']}\n"
            f"📍 Location: {job.get('location', 'India')}\n"
            f"🎓 Fresher: {job.get('fresher', 'Check listing')}\n"
            f"🕐 Posted: {job.get('date', 'Not stated')}\n\n"
            f"🔧 Match: {skills}\n\n"
            f"🔗 APPLY / VIEW:\n{job['link']}\n\n"
            "🎯 Embedded-related job"
        )

        try:
            send_telegram(message)
            print(f"Telegram alert sent: {job['title']}")

        except Exception as e:
            print("Telegram error:", e)

    print("\nJob Radar finished.")


if __name__ == "__main__":
    main()

