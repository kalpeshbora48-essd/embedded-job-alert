import os
import json
import hashlib
import re
import requests
import xml.etree.ElementTree as ET

from pathlib import Path
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from bs4 import BeautifulSoup

from ats_sources import fetch_ats_jobs


# ============================================================
# CONFIG
# ============================================================

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

DB_FILE = Path("seen_jobs.json")
COMPANIES_FILE = Path("companies.txt")

# Maximum age allowed for a job when a reliable posting date exists.
# 7 days keeps the alert focused on genuinely fresh jobs.
MAX_JOB_AGE_DAYS = 7


# ============================================================
# LOCATIONS
# ============================================================

LOCATIONS = [
    "pune",
    "pimpri",
    "pimpri chinchwad",
    "mumbai",
    "navi mumbai",
    "thane",
    "bangalore",
    "bengaluru",
    "hyderabad"
]


# ============================================================
# EMBEDDED KEYWORDS
# ============================================================

EMBEDDED_KEYWORDS = [
    "embedded",
    "embedded systems",
    "embedded c",
    "embedded software",
    "embedded firmware",
    "firmware",
    "microcontroller",
    "microcontrollers",
    "mcu",
    "stm32",
    "arm cortex",
    "arm",
    "rtos",
    "freertos",
    "iot",
    "electronics",
    "electronic",
    "hardware",
    "board bring-up",
    "board bringup",
    "device driver",
    "device drivers",
    "bare metal",
    "bootloader",
    "uart",
    "spi",
    "i2c",
    "can protocol",
    "can bus",
    "embedded linux",
    "linux driver",
    "device firmware"
]


# ============================================================
# FRESHER / ENTRY LEVEL
# ============================================================

FRESHER_KEYWORDS = [
    "fresher",
    "freshers",
    "fresh graduate",
    "recent graduate",
    "entry level",
    "entry-level",
    "entrylevel",
    "graduate",
    "trainee",
    "intern",
    "internship",
    "junior",
    "0 year",
    "0 years",
    "0-1 year",
    "0 - 1 year",
    "0–1 year",
    "0-2 years",
    "0 - 2 years",
    "0–2 years",
    "0 to 1 year",
    "0 to 2 years",
    "1 year",
    "1 years"
]


# ============================================================
# EXPERIENCED / EXCLUDE
# ============================================================

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
# GOOGLE NEWS RSS
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
# HTTP
# ============================================================

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "Chrome/131.0 Safari/537.36 "
        "EmbeddedJobMonitor/2.0"
    )
}


# ============================================================
# TEXT CLEANING
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


def normalize_text(text):

    text = clean_html(text)

    text = text.lower()

    text = re.sub(
        r"\s+",
        " ",
        text
    )

    return text.strip()


# ============================================================
# URL NORMALIZATION
# ============================================================

def canonical_url(url):

    if not url:
        return ""

    url = url.strip()

    try:

        parsed = urlparse(url)

        if not parsed.scheme:
            return ""

        host = parsed.netloc.lower()

        if host.startswith("www."):
            host = host[4:]

        path = parsed.path.rstrip("/")

        # Remove tracking parameters.
        ignored = {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_term",
            "utm_content",
            "gclid",
            "fbclid",
            "ref",
            "source"
        }

        query_items = []

        for key, value in parse_qsl(
            parsed.query,
            keep_blank_values=True
        ):

            if key.lower() not in ignored:
                query_items.append(
                    (key, value)
                )

        query = urlencode(
            query_items
        )

        return urlunparse(
            (
                "https",
                host,
                path,
                "",
                query,
                ""
            )
        )

    except Exception:

        return url


# ============================================================
# URL VALIDATION
# ============================================================

def is_valid_apply_url(url):

    if not url:
        return False

    url = canonical_url(url)

    if not url:
        return False

    parsed = urlparse(url)

    if parsed.scheme not in {
        "http",
        "https"
    }:
        return False

    host = parsed.netloc.lower()

    if not host:
        return False

    # Reject obvious search/discovery pages.
    bad_paths = [
        "/careers",
        "/career",
        "/jobs",
        "/job-search",
        "/search",
        "/search-jobs",
        "/jobsearch",
        "/vacancies"
    ]

    path = parsed.path.lower().rstrip("/")

    if path in bad_paths:
        return False

    return True


# ============================================================
# LOCATION
# ============================================================

def find_location(text):

    text = normalize_text(text)

    for location in LOCATIONS:

        if location in text:
            return location.title()

    return ""


# ============================================================
# SKILLS / EMBEDDED MATCH
# ============================================================

def embedded_match(text):

    text = normalize_text(text)

    matched = []

    for keyword in EMBEDDED_KEYWORDS:

        if keyword in text:
            matched.append(keyword)

    return list(dict.fromkeys(matched))


# ============================================================
# EXPERIENCE
# ============================================================

def fresher_status(text):

    text = normalize_text(text)

    for keyword in FRESHER_KEYWORDS:

        if keyword in text:
            return True

    return False


def experienced_role(text):

    text = normalize_text(text)

    for keyword in EXPERIENCED_KEYWORDS:

        if keyword in text:
            return True

    return False


def extract_experience(text):

    text = normalize_text(text)

    patterns = [
        r"\b0\s*[-–]\s*1\s*years?\b",
        r"\b0\s*[-–]\s*2\s*years?\b",
        r"\b0\s*to\s*1\s*years?\b",
        r"\b0\s*to\s*2\s*years?\b",
        r"\b1\s*years?\b",
        r"\bfresher\b",
        r"\bfreshers\b",
        r"\bentry[- ]level\b",
        r"\bgraduate\b",
        r"\bintern(ship)?\b",
        r"\btrainee\b"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            return match.group(0)

    return "Entry level"


# ============================================================
# SALARY
# ============================================================

def extract_salary(text):

    text = clean_html(text)

    patterns = [

        r"(?:₹|rs\.?|inr)\s*[\d,.]+\s*(?:lpa|lakhs?|lakh|cr|crore)?"
        r"(?:\s*[-–to]+\s*"
        r"(?:₹|rs\.?|inr)?\s*[\d,.]+\s*(?:lpa|lakhs?|lakh|cr|crore)?)?",

        r"\b\d+(?:\.\d+)?\s*(?:lpa|lakhs?|lakh)\b"
        r"(?:\s*[-–to]+\s*\d+(?:\.\d+)?\s*(?:lpa|lakhs?|lakh))?",

        r"\$\s*[\d,.]+"
        r"(?:\s*[-–to]+\s*\$?\s*[\d,.]+)?"
    ]

    for pattern in patterns:

        match = re.search(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            value = match.group(0).strip()

            if len(value) <= 80:
                return value

    return ""


# ============================================================
# DATE PARSING
# ============================================================

def parse_date(value):

    if not value:
        return None

    if isinstance(value, datetime):
        return value

    text = str(value).strip()

    if not text:
        return None

    # ISO date/time.
    try:

        iso = text.replace(
            "Z",
            "+00:00"
        )

        dt = datetime.fromisoformat(
            iso
        )

        if dt.tzinfo is None:

            dt = dt.replace(
                tzinfo=timezone.utc
            )

        return dt.astimezone(
            timezone.utc
        )

    except Exception:
        pass

    formats = [
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S GMT",
        "%d %b %Y",
        "%d %B %Y",
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%m/%d/%Y",
        "%d/%m/%Y"
    ]

    for fmt in formats:

        try:

            dt = datetime.strptime(
                text,
                fmt
            )

            if dt.tzinfo is None:

                dt = dt.replace(
                    tzinfo=timezone.utc
                )

            return dt.astimezone(
                timezone.utc
            )

        except Exception:
            continue

    # Relative dates.
    relative = re.search(
        r"(\d+)\s*(day|days|hour|hours|week|weeks)\s*ago",
        text.lower()
    )

    if relative:

        number = int(
            relative.group(1)
        )

        unit = relative.group(2)

        now = datetime.now(
            timezone.utc
        )

        if "hour" in unit:

            return now - timedelta(
                hours=number
            )

        if "day" in unit:

            return now - timedelta(
                days=number
            )

        if "week" in unit:

            return now - timedelta(
                weeks=number
            )

    if text.lower() in {
        "today",
        "just now"
    }:

        return datetime.now(
            timezone.utc
        )

    if text.lower() == "yesterday":

        return (
            datetime.now(
                timezone.utc
            )
            - timedelta(days=1)
        )

    return None


# ============================================================
# FRESHNESS
# ============================================================

def is_recent_job(date_value):

    dt = parse_date(
        date_value
    )

    # If source provides no reliable date,
    # do NOT trust it as a fresh job.
    if dt is None:
        return False

    now = datetime.now(
        timezone.utc
    )

    # Future timestamps are suspicious.
    if dt > now + timedelta(
        minutes=10
    ):
        return False

    age = now - dt

    if age < timedelta(
        minutes=-10
    ):
        return False

    if age > timedelta(
        days=MAX_JOB_AGE_DAYS
    ):
        return False

    return True


# ============================================================
# RELEVANCE
# ============================================================

def is_relevant(
    title,
    description
):

    title = title or ""
    description = description or ""

    combined = (
        title
        + " "
        + description
    )

    skills = embedded_match(
        combined
    )

    if not skills:

        return (
            False,
            "",
            "",
            [],
            ""
        )

    location = find_location(
        combined
    )

    if not location:

        return (
            False,
            "",
            "",
            skills,
            ""
        )

    if experienced_role(
        title
    ):

        return (
            False,
            location,
            "",
            skills,
            ""
        )

    experience = extract_experience(
        combined
    )

    salary = extract_salary(
        combined
    )

    # We want fresher/entry-level roles.
    # If the description clearly says an experienced
    # range such as 3+ years, reject it.
    experience_lower = normalize_text(
        combined
    )

    bad_experience_patterns = [
        r"\b[2-9]\s*\+\s*years?\b",
        r"\b1[0-9]\s*\+\s*years?\b",
        r"\b[3-9]\s*years?\s*(?:of)?\s*experience\b",
        r"\b1[0-9]\s*years?\s*(?:of)?\s*experience\b"
    ]

    for pattern in bad_experience_patterns:

        if re.search(
            pattern,
            experience_lower
        ):

            return (
                False,
                location,
                experience,
                skills,
                salary
            )

    return (
        True,
        location,
        experience,
        skills,
        salary
    )


# ============================================================
# DATABASE
# ============================================================

def load_seen():

    if not DB_FILE.exists():
        return {}

    try:

        data = json.loads(
            DB_FILE.read_text(
                encoding="utf-8"
            )
        )

        if isinstance(data, dict):
            return data

        if isinstance(data, list):

            return {
                str(item): {
                    "sent_at": ""
                }
                for item in data
            }

    except Exception as error:

        print(
            "Database read error:",
            error
        )

    return {}


def save_seen(seen):

    DB_FILE.write_text(
        json.dumps(
            seen,
            indent=2,
            ensure_ascii=False
        ),
        encoding="utf-8"
    )


# ============================================================
# DUPLICATE KEY
# ============================================================

def job_id(
    title,
    link,
    company=""
):

    normalized_title = normalize_text(
        title
    )

    normalized_company = normalize_text(
        company
    )

    normalized_link = canonical_url(
        link
    )

    # URL is strongest identifier.
    if normalized_link:

        value = (
            "url|"
            + normalized_link
        )

    else:

        value = (
            "job|"
            + normalized_company
            + "|"
            + normalized_title
        )

    return hashlib.sha256(
        value.encode(
            "utf-8"
        )
    ).hexdigest()


# ============================================================
# RSS
# ============================================================

def read_feed(feed_url):

    jobs = []

    try:

        response = requests.get(
            feed_url,
            headers=HEADERS,
            timeout=20
        )

        if response.status_code != 200:

            print(
                "RSS failed:",
                response.status_code,
                feed_url
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

                "title":
                    clean_html(title),

                "link":
                    canonical_url(link),

                "description":
                    clean_html(description),

                "date":
                    date,

                "source":
                    "Google News"

            })

    except Exception as error:

        print(
            "RSS error:",
            error
        )

    return jobs


# ============================================================
# COMPANIES
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

        companies.append(
            line
        )

    return companies


# ============================================================
# CAREER DISCOVERY
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


def discover_career_links(
    domain
):

    links = set()

    if not domain.startswith(
        "http"
    ):

        domain = (
            "https://"
            + domain
        )

    try:

        response = requests.get(
            domain,
            headers=HEADERS,
            timeout=20
        )

        if response.status_code != 200:

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
            )

            if not href:
                continue

            if href.startswith("/"):

                href = (
                    domain.rstrip("/")
                    + href
                )

            elif href.startswith("//"):

                href = (
                    "https:"
                    + href
                )

            combined = (
                text
                + " "
                + href
            ).lower()

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

                links.add(
                    href
                )

            if any(
                ats in href.lower()
                for ats in ATS_DOMAINS
            ):

                links.add(
                    href
                )

    except Exception as error:

        print(
            "Career discovery error:",
            error
        )

    return list(
        links
    )


# ============================================================
# PUBLIC CAREER PAGE
# ============================================================

def read_public_career_page(
    career_url,
    company_domain
):

    jobs = []

    try:

        response = requests.get(
            career_url,
            headers=HEADERS,
            timeout=20
        )

        if response.status_code != 200:
            return jobs

        soup = BeautifulSoup(
            response.text,
            "html.parser"
        )

        page_text = soup.get_text(
            " ",
            strip=True
        )

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

            if len(title) < 5:
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

            if not is_valid_apply_url(
                href
            ):
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

            jobs.append({

                "title":
                    title,

                "link":
                    canonical_url(href),

                "description":
                    page_text,

                "date":
                    "",

                "source":
                    company_domain

            })

    except Exception as error:

        print(
            "Career page error:",
            error
        )

    return jobs


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(
    message
):

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

        return (
            response.status_code == 200
        )

    except Exception as error:

        print(
            "Telegram error:",
            error
        )

        return False


# ============================================================
# TELEGRAM MESSAGE
# ============================================================

def format_job(
    job
):

    title = job.get(
        "title",
        "Unknown role"
    )

    link = canonical_url(
        job.get(
            "link",
            ""
        )
    )

    location = job.get(
        "location",
        "Not specified"
    )

    experience = job.get(
        "experience",
        "Entry level"
    )

    salary = job.get(
        "salary",
        ""
    )

    message = (
        "🚨 NEW JOB\n\n"
        "💼 Role: "
        + title
        + "\n"
        "📍 Location: "
        + location
        + "\n"
        "🎓 Experience: "
        + experience
        + "\n"
    )

    if salary:

        message += (
            "💰 Salary: "
            + salary
            + "\n"
        )

    message += (
        "\n🔗 Apply:\n"
        + link
    )

    return message


# ============================================================
# PROCESS JOB
# ============================================================

def process_job(
    job,
    seen,
    new_jobs
):

    title = job.get(
        "title",
        ""
    ).strip()

    link = canonical_url(
        job.get(
            "link",
            ""
        )
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

    if not title:
        return

    if not is_valid_apply_url(
        link
    ):

        print(
            "Rejected: invalid apply URL:",
            title
        )

        return

    # --------------------------------------------------------
    # FRESHNESS
    # --------------------------------------------------------

    if not is_recent_job(
        date
    ):

        print(
            "Rejected: old/unknown date:",
            title,
            date
        )

        return

    # --------------------------------------------------------
    # RELEVANCE
    # --------------------------------------------------------

    (
        relevant,
        location,
        experience,
        skills,
        salary
    ) = is_relevant(
        title,
        description
    )

    if not relevant:

        return

    # --------------------------------------------------------
    # DUPLICATE
    # --------------------------------------------------------

    identifier = job_id(
        title,
        link
    )

    if identifier in seen:

        print(
            "Already sent:",
            title
        )

        return

    # --------------------------------------------------------
    # SAVE DATA
    # --------------------------------------------------------

    job["title"] = title

    job["link"] = link

    job["location"] = location

    job["experience"] = experience

    job["salary"] = salary

    job["skills"] = skills

    job["source"] = source

    job["_id"] = identifier

    new_jobs.append(
        job
    )


# ============================================================
# MAIN
# ============================================================

def main():

    print(
        "\n======================================"
    )

    print(
        "     EMBEDDED JOB MONITOR v3"
    )

    print(
        "======================================\n"
    )

    seen = load_seen()

    new_jobs = []

    # ========================================================
    # RSS SOURCES
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

            process_job(
                job,
                seen,
                new_jobs
            )

    # ========================================================
    # COMPANY SOURCES
    # ========================================================

    print(
        "\n[2] Checking company sources..."
    )

    companies = load_companies()

    for domain in companies:

        print(
            "\nCompany:",
            domain
        )

        career_links = (
            discover_career_links(
                domain
            )
        )

        # ----------------------------------------------------
        # ATS
        # ----------------------------------------------------

        try:

            ats_jobs = (
                fetch_ats_jobs(
                    career_links
                )
            )

            print(
                "ATS jobs found:",
                len(ats_jobs)
            )

        except Exception as error:

            print(
                "ATS error:",
                error
            )

            ats_jobs = []

        for job in ats_jobs:

            process_job(
                job,
                seen,
                new_jobs
            )

        # ----------------------------------------------------
        # PUBLIC CAREER PAGES
        # ----------------------------------------------------

        for career_url in career_links:

            jobs = (
                read_public_career_page(
                    career_url,
                    domain
                )
            )

            for job in jobs:

                process_job(
                    job,
                    seen,
                    new_jobs
                )

    # ========================================================
    # REMOVE DUPLICATES INSIDE THIS RUN
    # ========================================================

    unique_jobs = []

    current_run_ids = set()

    for job in new_jobs:

        identifier = job.get(
            "_id"
        )

        if identifier in current_run_ids:
            continue

        current_run_ids.add(
            identifier
        )

        unique_jobs.append(
            job
        )

    new_jobs = unique_jobs

    print(
        "\nNew jobs ready:",
        len(new_jobs)
    )

    # ========================================================
    # SEND
    # ========================================================

    for job in new_jobs:

        message = format_job(
            job
        )

        success = send_telegram(
            message
        )

        if success:

            identifier = job.get(
                "_id"
            )

            # Mark as sent ONLY after Telegram succeeds.
            seen[identifier] = {
                "title":
                    job.get(
                        "title",
                        ""
                    ),

                "link":
                    job.get(
                        "link",
                        ""
                    ),

                "sent_at":
                    datetime.now(
                        timezone.utc
                    ).isoformat()
            }

            print(
                "SENT:",
                job.get(
                    "title",
                    ""
                )
            )

        else:

            print(
                "TELEGRAM FAILED:",
                job.get(
                    "title",
                    ""
                )
            )

    # ========================================================
    # SAVE
    # ========================================================

    save_seen(
        seen
    )

    print(
        "\nDatabase entries:",
        len(seen)
    )

    print(
        "Monitor completed."
    )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()
