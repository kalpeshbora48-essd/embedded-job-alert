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
# CONFIGURATION
# ============================================================

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

DB_FILE = Path("seen_jobs.json")
COMPANIES_FILE = Path("companies.txt")


# ============================================================
# JOB PREFERENCES
# ============================================================

LOCATIONS = [
    "pune",
    "pimpri",
    "mumbai",
    "bangalore",
    "bengaluru",
    "hyderabad"
]


EMBEDDED_KEYWORDS = [
    "embedded",
    "embedded systems",
    "embedded c",
    "firmware",
    "microcontroller",
    "microcontroller",
    "mcu",
    "stm32",
    "arm cortex",
    "rtos",
    "freertos",
    "iot",
    "electronics",
    "hardware",
    "board bring-up",
    "board bringup",
    "device driver",
    "bare metal",
    "bootloader",
    "uart",
    "spi",
    "i2c",
    "can protocol",
    "can bus"
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
    "0 - 1 year",
    "0-2 years",
    "0 - 2 years",
    "0 to 1 year",
    "0 to 2 years",
    "1 year",
    "1 years"
]


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
    "9+ years",
    "10+ years",
    "5 years",
    "6 years",
    "7 years",
    "8 years",
    "9 years",
    "10 years"
]


# ============================================================
# GOOGLE NEWS RSS SOURCES
# ============================================================

RSS_FEEDS = [

    "https://news.google.com/rss/search?q=embedded+jobs+Pune",

    "https://news.google.com/rss/search?q=embedded+jobs+Mumbai",

    "https://news.google.com/rss/search?q=embedded+jobs+Bangalore",

    "https://news.google.com/rss/search?q=embedded+jobs+Hyderabad",

    "https://news.google.com/rss/search?q=firmware+jobs+India",

    "https://news.google.com/rss/search?q=embedded+C+jobs+India",

    "https://news.google.com/rss/search?q=IoT+jobs+India",

    "https://news.google.com/rss/search?q=electronics+jobs+India",

    "https://news.google.com/rss/search?q=STM32+jobs+India",

    "https://news.google.com/rss/search?q=RTOS+embedded+jobs+India"
]


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):

    url = (
        "https://api.telegram.org/bot"
        + BOT_TOKEN
        + "/sendMessage"
    )

    payload = {
        "chat_id": CHAT_ID,
        "text": message,
        "disable_web_page_preview": False
    }

    try:

        response = requests.post(
            url,
            json=payload,
            timeout=20
        )

        return response.status_code == 200

    except Exception as error:

        print("Telegram error:", error)

        return False


# ============================================================
# DATABASE
# ============================================================

def load_seen():

    if not DB_FILE.exists():
        return set()

    try:

        data = json.loads(
            DB_FILE.read_text(
                encoding="utf-8"
            )
        )

        return set(data)

    except Exception:

        return set()


def save_seen(seen):

    DB_FILE.write_text(
        json.dumps(
            sorted(seen),
            indent=2
        ),
        encoding="utf-8"
    )


def job_id(title, link):

    value = (
        str(title).strip().lower()
        + "|"
        + str(link).strip().lower()
    )

    return hashlib.sha256(
        value.encode("utf-8")
    ).hexdigest()


# ============================================================
# TEXT HELPERS
# ============================================================

def clean_html(text):

    if not text:
        return ""

    return BeautifulSoup(
        str(text),
        "html.parser"
    ).get_text(
        " ",
        strip=True
    )


def get_domain(url):

    try:

        return urlparse(url).netloc.lower()

    except Exception:

        return ""


def find_location(text):

    text = text.lower()

    for location in LOCATIONS:

        if location in text:
            return location.title()

    return ""


def embedded_match(text):

    text = text.lower()

    matched = []

    for keyword in EMBEDDED_KEYWORDS:

        if keyword.lower() in text:

            matched.append(keyword)

    return matched


def fresher_status(text):

    text = text.lower()

    matched = []

    for keyword in FRESHER_KEYWORDS:

        if keyword.lower() in text:

            matched.append(keyword)

    if matched:
        return True

    return False


def experienced_role(text):

    text = text.lower()

    for keyword in EXPERIENCED_KEYWORDS:

        if keyword.lower() in text:

            return True

    return False


# ============================================================
# JOB FILTER
# ============================================================

def is_relevant(title, description):

    title = title or ""
    description = description or ""

    combined = (
        title
        + " "
        + description
    ).lower()

    # --------------------------------------------------------
    # Embedded-related check
    # --------------------------------------------------------

    skills = embedded_match(combined)

    if not skills:
        return (
            False,
            "",
            False,
            []
        )

    # --------------------------------------------------------
    # Location check
    # --------------------------------------------------------

    location = find_location(combined)

    if not location:

        return (
            False,
            "",
            False,
            skills
        )

    # --------------------------------------------------------
    # Experienced-role exclusion
    # --------------------------------------------------------

    if experienced_role(combined):

        return (
            False,
            location,
            False,
            skills
        )

    # --------------------------------------------------------
    # Fresher detection
    # --------------------------------------------------------

    fresher = fresher_status(combined)

    # If experience is not explicitly mentioned,
    # we still allow the job because many company pages
    # do not expose experience information.
    return (
        True,
        location,
        fresher,
        skills
    )


# ============================================================
# RSS READER
# ============================================================

def read_feed(feed_url):

    jobs = []

    try:

        response = requests.get(
            feed_url,
            timeout=20,
            headers={
                "User-Agent":
                "Mozilla/5.0 EmbeddedJobMonitor/1.0"
            }
        )

        if response.status_code != 200:

            print(
                "RSS failed:",
                feed_url,
                response.status_code
            )

            return jobs

        root = ET.fromstring(
            response.content
        )

        for item in root.findall(
            ".//item"
        ):

            title = item.findtext(
                "title",
                default=""
            )

            link = item.findtext(
                "link",
                default=""
            )

            description = item.findtext(
                "description",
                default=""
            )

            date = item.findtext(
                "pubDate",
                default=""
            )

            jobs.append({

                "title": clean_html(title),

                "link": link.strip(),

                "description":
                    clean_html(description),

                "date": date,

                "source":
                    get_domain(link)

            })

    except Exception as error:

        print(
            "RSS error:",
            feed_url,
            error
        )

    return jobs


# ============================================================
# COMPANY LIST
# ============================================================

def load_companies():

    if not COMPANIES_FILE.exists():

        print(
            "companies.txt not found"
        )

        return []

    companies = []

    for line in COMPANIES_FILE.read_text(
        encoding="utf-8"
    ).splitlines():

        line = line.strip()

        if not line:
            continue

        if line.startswith("#"):
            continue

        companies.append(line)

    return companies


# ============================================================
# ATS DOMAINS
# ============================================================

ATS_DOMAINS = [

    "greenhouse.io",

    "lever.co",

    "ashbyhq.com",

    "smartrecruiters.com",

    "recruitee.com",

    "breezy.hr",

    "teamtailor.com",

    "personio.com",

    "bamboohr.com",

    "workable.com",

    "rippling.com"
]


# ============================================================
# CAREER LINK DISCOVERY
# ============================================================

def discover_career_links(domain):

    links = set()

    if not domain.startswith("http"):

        domain = (
            "https://"
            + domain
        )

    try:

        response = requests.get(
            domain,
            headers={
                "User-Agent":
                "Mozilla/5.0 EmbeddedJobMonitor/1.0"
            },
            timeout=20
        )

        if response.status_code != 200:

            print(
                "Company page failed:",
                domain,
                response.status_code
            )

            return []

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        for anchor in soup.find_all(
            "a",
            href=True
        ):

            href = anchor.get(
                "href",
                ""
            ).strip()

            text = anchor.get_text(
                " ",
                strip=True
            ).lower()

            if not href:
                continue

            # ------------------------------------------------
            # Convert relative URLs
            # ------------------------------------------------

            if href.startswith("/"):

                base = domain.rstrip("/")

                href = (
                    base
                    + href
                )

            elif href.startswith("//"):

                href = (
                    "https:"
                    + href
                )

            # ------------------------------------------------
            # Career/job links
            # ------------------------------------------------

            combined = (
                text
                + " "
                + href.lower()
            )

            if any(
                keyword in combined
                for keyword in [
                    "career",
                    "careers",
                    "jobs",
                    "job",
                    "vacancy",
                    "work-with-us",
                    "work with us"
                ]
            ):

                links.add(href)

            # ------------------------------------------------
            # ATS links
            # ------------------------------------------------

            if any(
                ats in href.lower()
                for ats in ATS_DOMAINS
            ):

                links.add(href)

    except Exception as error:

        print(
            "Career discovery error:",
            domain,
            error
        )

    return list(links)


# ============================================================
# GENERIC PUBLIC CAREER PAGE READER
# ============================================================

def read_public_career_page(
    career_url,
    company_domain
):

    jobs = []

    try:

        response = requests.get(
            career_url,
            headers={
                "User-Agent":
                "Mozilla/5.0 EmbeddedJobMonitor/1.0"
            },
            timeout=20
        )

        if response.status_code != 200:

            return jobs

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        page_text = soup.get_text(
            "\n",
            strip=True
        )

        # ----------------------------------------------------
        # Look for links that appear to be job postings
        # ----------------------------------------------------

        for anchor in soup.find_all(
            "a",
            href=True
        ):

            title = anchor.get_text(
                " ",
                strip=True
            )

            href = anchor.get(
                "href",
                ""
            ).strip()

            if not title:
                continue

            if len(title) < 5:
                continue

            combined = (
                title
                + " "
                + href
            ).lower()

            if not any(
                keyword in combined
                for keyword in [
                    "job",
                    "career",
                    "position",
                    "opening",
                    "vacancy",
                    "engineer",
                    "developer",
                    "intern",
                    "trainee",
                    "firmware",
                    "embedded"
                ]
            ):

                continue

            if href.startswith("/"):

                parsed = urlparse(
                    career_url
                )

                href = (
                    parsed.scheme
                    + "://"
                    + parsed.netloc
                    + href
                )

            elif href.startswith("//"):

                href = (
                    "https:"
                    + href
                )

            elif not href.startswith(
                "http"
            ):

                continue

            jobs.append({

                "title": title,

                "link": href,

                "description":
                    page_text,

                "date": "",

                "source":
                    company_domain

            })

    except Exception as error:

        print(
            "Career page error:",
            career_url,
            error
        )

    return jobs


# ============================================================
# FORMAT TELEGRAM MESSAGE
# ============================================================

def format_job(job):

    title = job.get(
        "title",
        "Unknown role"
    )

    link = job.get(
        "link",
        ""
    )

    description = job.get(
        "description",
        ""
    )

    date = job.get(
        "date",
        ""
    )

    source = job.get(
        "source",
        ""
    )

    location = job.get(
        "location",
        ""
    )

    fresher = job.get(
        "fresher",
        False
    )

    skills = job.get(
        "skills",
        []
    )

    if fresher:

        experience_text = (
            "Fresher / Entry Level"
        )

    else:

        experience_text = (
            "Entry-level match"
        )

    if not location:

        location = "Not specified"

    if not source:

        source = "Company / Job Source"

    skill_text = ", ".join(
        skills[:8]
    )

    message = (
        "🚨 NEW EMBEDDED JOB\n\n"

        "💼 Role: "
        + title
        + "\n\n"

        "📍 Location: "
        + location
        + "\n\n"

        "🎓 Experience: "
        + experience_text
        + "\n\n"

        "🛠 Skills: "
        + skill_text
        + "\n\n"

        "🏢 Source: "
        + source
        + "\n\n"
    )

    if date:

        message += (
            "🕒 Posted: "
            + str(date)
            + "\n\n"
        )

    message += (
        "🔗 APPLY DIRECTLY:\n"
        + link
    )

    return message


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "\n========================================"
    )

    print(
        "     EMBEDDED JOB MONITOR"
    )

    print(
        "========================================\n"
    )

    seen = load_seen()

    new_jobs = []

    # ========================================================
    # 1. GOOGLE NEWS RSS
    # ========================================================

    print(
        "[1] Checking RSS sources..."
    )

    for feed_url in RSS_FEEDS:

        print(
            "RSS:",
            feed_url
        )

        jobs = read_feed(
            feed_url
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

            job["location"] = location

            job["fresher"] = fresher

            job["skills"] = skills

            seen.add(
                identifier
            )

            new_jobs.append(
                job
            )

    # ========================================================
    # 2. COMPANY CAREER PAGES + ATS
    # ========================================================

    print(
        "\n[2] Checking company career pages..."
    )

    companies = load_companies()

    for domain in companies:

        print(
            "Discovering:",
            domain
        )

        career_links = (
            discover_career_links(
                domain
            )
        )

        # ----------------------------------------------------
        # DIRECT ATS SOURCES
        # ----------------------------------------------------

        print(
            "Checking ATS:",
            domain
        )

        try:

            ats_jobs = (
                fetch_ats_jobs(
                    career_links
                )
            )

        except Exception as error:

            print(
                "ATS error:",
                domain,
                error
            )

            ats_jobs = []

        for job in ats_jobs:

            relevant, location, fresher, skills = is_relevant(
                job.get(
                    "title",
                    ""
                ),
                job.get(
                    "description",
                    ""
                )
            )

            if not relevant:
                continue

            identifier = job_id(
                job.get(
                    "title",
                    ""
                ),
                job.get(
                    "link",
                    ""
                )
            )

            if identifier in seen:
                continue

            job["location"] = location

            job["fresher"] = fresher

            job["skills"] = skills

            seen.add(
                identifier
            )

            new_jobs.append(
                job
            )

        # ----------------------------------------------------
        # NORMAL PUBLIC CAREER PAGES
        # ----------------------------------------------------

        for career_url in career_links:

            print(
                "Reading:",
                career_url
            )

            jobs = (
                read_public_career_page(
                    career_url,
                    domain
                )
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

                job["location"] = location

                job["fresher"] = fresher

                job["skills"] = skills

                seen.add(
                    identifier
                )

                new_jobs.append(
                    job
                )

    # ========================================================
    # SAVE DATABASE
    # ========================================================

    save_seen(
        seen
    )

    # ========================================================
    # TELEGRAM ALERTS
    # ========================================================

    print(
        "\nNew matching jobs:",
        len(new_jobs)
    )

    if not new_jobs:

        print(
            "No new matching jobs."
        )

        return

    print(
        "Sending Telegram alerts..."
    )

    for job in new_jobs:

        message = format_job(
            job
        )

        success = send_telegram(
            message
        )

        if success:

            print(
                "Alert sent:",
                job.get(
                    "title",
                    ""
                )
            )

        else:

            print(
                "Alert failed:",
                job.get(
                    "title",
                    ""
                )
            )

    print(
        "\nMonitor completed successfully."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
