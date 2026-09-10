import requests
from urllib.parse import urlparse, quote
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (EmbeddedJobMonitor/1.0)"
}

TIMEOUT = 15


def clean_text(value):
    if not value:
        return ""
    return BeautifulSoup(str(value), "html.parser").get_text(" ", strip=True)


def make_job(title, link, description="", date="", source="ATS"):
    return {
        "title": clean_text(title),
        "link": link,
        "description": clean_text(description),
        "date": date or "",
        "source": source
    }


def get_json(url):
    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT
        )

        if response.status_code != 200:
            return None

        return response.json()

    except Exception:
        return None


# ---------------------------------------------------------
# GREENHOUSE
# ---------------------------------------------------------

def greenhouse_jobs(board_token):
    url = (
        "https://boards-api.greenhouse.io/v1/boards/"
        + quote(board_token)
        + "/jobs?content=true"
    )

    data = get_json(url)

    if not data:
        return []

    jobs = []

    for job in data.get("jobs", []):
        jobs.append(
            make_job(
                job.get("title"),
                job.get("absolute_url"),
                job.get("content"),
                job.get("updated_at"),
                "Greenhouse"
            )
        )

    return jobs


# ---------------------------------------------------------
# LEVER
# ---------------------------------------------------------

def lever_jobs(company):
    url = (
        "https://api.lever.co/v0/postings/"
        + quote(company)
        + "?mode=json"
    )

    data = get_json(url)

    if not data or not isinstance(data, list):
        return []

    jobs = []

    for job in data:
        description = job.get("descriptionPlain", "")
        if not description:
            description = job.get("description", "")

        jobs.append(
            make_job(
                job.get("text"),
                job.get("hostedUrl"),
                description,
                job.get("createdAt", ""),
                "Lever"
            )
        )

    return jobs


# ---------------------------------------------------------
# ASHBY
# ---------------------------------------------------------

def ashby_jobs(board_name):
    url = (
        "https://api.ashbyhq.com/posting-api/job-board/"
        + quote(board_name)
    )

    data = get_json(url)

    if not data:
        return []

    jobs = []

    for job in data.get("jobs", []):
        jobs.append(
            make_job(
                job.get("title"),
                job.get("jobUrl") or job.get("applyUrl"),
                job.get("description"),
                job.get("publishedAt"),
                "Ashby"
            )
        )

    return jobs


# ---------------------------------------------------------
# SMARTRECRUITERS
# ---------------------------------------------------------

def smartrecruiters_jobs(company):
    url = (
        "https://api.smartrecruiters.com/v1/companies/"
        + quote(company)
        + "/postings?limit=100"
    )

    data = get_json(url)

    if not data:
        return []

    jobs = []

    for job in data.get("content", []):
        ref = job.get("ref")

        link = ""

        if ref:
            link = (
                "https://jobs.smartrecruiters.com/"
                + company
                + "/"
                + str(ref)
            )

        location = job.get("location", {})

        description = ""
        if isinstance(location, dict):
            description = (
                location.get("city", "")
                + " "
                + location.get("country", "")
            )

        jobs.append(
            make_job(
                job.get("name"),
                link,
                description,
                job.get("releasedDate"),
                "SmartRecruiters"
            )
        )

    return jobs


# ---------------------------------------------------------
# RECRUITEE
# ---------------------------------------------------------

def recruitee_jobs(company):
    url = (
        "https://"
        + quote(company)
        + ".recruitee.com/api/offers/"
    )

    data = get_json(url)

    if not data:
        return []

    jobs = []

    for job in data.get("offers", []):
        slug = job.get("slug", "")
        link = (
            "https://"
            + company
            + ".recruitee.com/l/"
            + slug
        )

        jobs.append(
            make_job(
                job.get("title"),
                link,
                job.get("description"),
                job.get("created_at"),
                "Recruitee"
            )
        )

    return jobs


# ---------------------------------------------------------
# TEAMTAILOR
# ---------------------------------------------------------

def teamtailor_jobs(company):
    url = (
        "https://"
        + quote(company)
        + ".teamtailor.com/jobs"
    )

    try:
        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT
        )

        if response.status_code != 200:
            return []

        soup = BeautifulSoup(response.text, "html.parser")

        jobs = []

        for link in soup.find_all("a", href=True):

            href = link.get("href", "")
            title = link.get_text(" ", strip=True)

            if "/jobs/" not in href:
                continue

            if not title:
                continue

            if href.startswith("/"):
                href = "https://" + company + ".teamtailor.com" + href

            jobs.append(
                make_job(
                    title,
                    href,
                    "",
                    "",
                    "Teamtailor"
                )
            )

        return jobs

    except Exception:
        return []


# ---------------------------------------------------------
# DETECT ATS FROM CAREER LINK
# ---------------------------------------------------------

def detect_ats(url):

    if not url:
        return None

    host = urlparse(url).netloc.lower()
    path = urlparse(url).path.lower()

    # Greenhouse
    if "greenhouse.io" in host:
        parts = path.strip("/").split("/")
        if parts:
            return ("greenhouse", parts[0])

    # Lever
    if "lever.co" in host:
        parts = path.strip("/").split("/")
        if parts:
            return ("lever", parts[0])

    # Ashby
    if "ashbyhq.com" in host:
        parts = path.strip("/").split("/")
        if parts:
            return ("ashby", parts[-1])

    # SmartRecruiters
    if "smartrecruiters.com" in host:
        parts = path.strip("/").split("/")

        if len(parts) >= 1:
            return ("smartrecruiters", parts[0])

    # Recruitee
    if "recruitee.com" in host:
        parts = host.split(".")

        if parts:
            return ("recruitee", parts[0])

    # Teamtailor
    if "teamtailor.com" in host:
        parts = host.split(".")

        if parts:
            return ("teamtailor", parts[0])

    return None


# ---------------------------------------------------------
# MAIN ATS FETCHER
# ---------------------------------------------------------

def fetch_ats_jobs(career_links):

    all_jobs = []

    checked = set()

    for career_link in career_links:

        detected = detect_ats(career_link)

        if not detected:
            continue

        ats, company = detected

        key = ats + ":" + company

        if key in checked:
            continue

        checked.add(key)

        try:

            if ats == "greenhouse":
                jobs = greenhouse_jobs(company)

            elif ats == "lever":
                jobs = lever_jobs(company)

            elif ats == "ashby":
                jobs = ashby_jobs(company)

            elif ats == "smartrecruiters":
                jobs = smartrecruiters_jobs(company)

            elif ats == "recruitee":
                jobs = recruitee_jobs(company)

            elif ats == "teamtailor":
                jobs = teamtailor_jobs(company)

            else:
                jobs = []

            all_jobs.extend(jobs)

        except Exception:
            continue

    return all_jobs
