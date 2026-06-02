import re
import time
from datetime import datetime
from bs4 import BeautifulSoup


# ── Module-level location validator ───────────────────────────────────────
_SKIP_LOCATION = re.compile(
    r"""
    (minute|hour|day|week|month|year)s?\s+ago   # relative time
    | \btoday\b | \bviewed\b | \bjust\s+now\b   # noise words
    | ^\$                                         # salary
    | ^(On[- ]?site|Remote|Hybrid|              # work-mode-only
       Full[- ]?time|Part[- ]?time|Contract)$
    """,
    re.I | re.VERBOSE,
)

_LOCATION_HINTS = re.compile(
    r"""
    ,                                             # "City, State" or "City, Country"
    | \b(United\s+States|India|Canada|Germany|
         France|Australia|UK|United\s+Kingdom|
         Singapore|Netherlands|Brazil|Japan|
         Mexico|Spain|Italy|Sweden|Israel|
         New\s+York|San\s+Francisco|California|
         London|Berlin|Toronto|Sydney|Bangalore|
         Bengaluru|Hyderabad|Mumbai|Pune|
         Chicago|Seattle|Austin|Boston|
         Los\s+Angeles|Denver|Atlanta|
         Remote|Worldwide|Global)\b
    """,
    re.I | re.VERBOSE,
)

# Phrases that indicate a company has no open jobs
_NO_JOBS_PHRASES = [
    "there are no jobs right now",
    "no jobs right now",
    "no matching jobs",
    "no results found",
    "0 results",
]


def _is_location(text: str) -> bool:
    """Return True if *text* looks like a job location."""
    if not text or len(text) < 3 or len(text) > 120:
        return False
    if _SKIP_LOCATION.search(text):
        return False
    return bool(_LOCATION_HINTS.search(text))


def _page_has_no_jobs(page_text: str) -> bool:
    """Return True if the page explicitly says there are no jobs."""
    lower = page_text.lower()
    return any(phrase in lower for phrase in _NO_JOBS_PHRASES)


class JobsScraper:

    def __init__(self, browser):
        self.browser = browser
        self.page    = browser.page

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    def scrape(self, slug: str, name: str) -> list:
        scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n💼 Jobs → {name}")

        jobs_url = f"https://www.linkedin.com/company/{slug}/jobs/"
        self.browser.goto(jobs_url)
        time.sleep(3)

        # ── Early exit: company page explicitly says no jobs ──────────
        page_text = self.page.inner_text("body")
        if _page_has_no_jobs(page_text):
            print(f"  ℹ  No jobs listed for {name} (page says 'no jobs')")
            return []

        # Extract numeric company ID from the page source — needed for
        # search URL filtering. Do this once while we're on the company page.
        company_id = self._extract_company_id_from_page()
        print(f"  🆔 Company ID: {company_id or 'not found'}")

        # ── Strategy 1: click "Show all jobs" button ──────────────────
        results = self._click_show_all_and_scrape(name, scraped_at, company_id)
        if results:
            print(f"  ✅ {len(results)} jobs via 'Show all jobs' click")
            return results

        # ── Strategy 2: parse job cards directly on the /jobs/ page ───
        results = self._scrape_company_jobs_page(name, scraped_at)
        if results:
            print(f"  ✅ {len(results)} jobs from company jobs page")
            return results

        # ── Strategy 3: search URL with numeric company ID filter ──────
        if company_id:
            results = self._try_search_url(company_id, name, scraped_at)
            if results:
                print(f"  ✅ {len(results)} jobs via search URL fallback")
                return results

        print(f"  ℹ  No jobs found for {name}")
        return []

    # ------------------------------------------------------------------
    # Strategy 1 – click "Show all jobs →" and scrape the search page
    # ------------------------------------------------------------------
    def _click_show_all_and_scrape(self, name: str, scraped_at: str,
                                    company_id: str) -> list:
        try:
            btn = None
            for sel in [
                'a:has-text("Show all jobs")',
                'a:has-text("See all jobs")',
                'button:has-text("Show all jobs")',
                'a[href*="jobs/search"]',
            ]:
                try:
                    el = self.page.locator(sel).first
                    if el.count() and el.is_visible():
                        btn = el
                        break
                except Exception:
                    continue

            if btn is None:
                print("  ⚠  No 'Show all jobs' button found")
                return []

            href = btn.get_attribute("href") or ""
            print(f"  🔗 Show-all href: {href[:80]}")

            with self.page.expect_navigation(wait_until="commit", timeout=20_000):
                btn.click()
            time.sleep(5)

            # Guard: if the search results page shows no jobs, bail out
            page_text = self.page.inner_text("body")
            if _page_has_no_jobs(page_text):
                print(f"  ℹ  Search page says no jobs for {name}")
                return []

            print(f"  📍 Landed on: {self.page.url}")
            return self._scrape_search_results_page(name, scraped_at, company_id)

        except Exception as e:
            print(f"  ⚠  Click strategy failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Strategy 2 – parse job cards on the /company/.../jobs/ page itself
    # ------------------------------------------------------------------
    def _scrape_company_jobs_page(self, name: str, scraped_at: str) -> list:
        try:
            html = self.page.content()
            soup = BeautifulSoup(html, "lxml")
            return self._parse_job_cards(soup, name, scraped_at)
        except Exception as e:
            print(f"  ⚠  Company jobs page parse failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Strategy 3 – search URL with numeric company ID
    # ------------------------------------------------------------------
    def _try_search_url(self, company_id: str, name: str, scraped_at: str) -> list:
        try:
            # f_C= must be the numeric LinkedIn company ID, not the slug
            search_url = (
                f"https://www.linkedin.com/jobs/search/"
                f"?f_C={company_id}&geoId=92000000"
            )
            print(f"  🔗 Trying search URL: {search_url}")
            self.browser.goto(search_url)
            time.sleep(5)

            page_text = self.page.inner_text("body")
            if _page_has_no_jobs(page_text):
                print(f"  ℹ  Search URL returned no jobs for {name}")
                return []

            return self._scrape_search_results_page(name, scraped_at, company_id)
        except Exception as e:
            print(f"  ⚠  Search URL fallback failed: {e}")
            return []

    # ------------------------------------------------------------------
    # Extract numeric company ID from the /company/{slug}/jobs/ page
    # ------------------------------------------------------------------
    def _extract_company_id_from_page(self) -> str:
        """Pull numeric company ID from the current page source."""
        try:
            html = self.page.content()
            # Try various patterns in the page source
            for pattern in [
                r'"companyId"\s*:\s*"?(\d+)"?',
                r'"entityUrn"\s*:\s*"urn:li:company:(\d+)"',
                r'f_C=(\d+)',
                r'/company/(\d+)/',
            ]:
                m = re.search(pattern, html)
                if m:
                    return m.group(1)
            # Also check the current URL
            m = re.search(r'f_C=(\d+)', self.page.url)
            if m:
                return m.group(1)
        except Exception:
            pass
        return ""

    # ------------------------------------------------------------------
    # Scrape a /jobs/search/ results page (left-panel list of jobs)
    # ------------------------------------------------------------------
    def _scrape_search_results_page(self, name: str, scraped_at: str,
                                     company_id: str = "") -> list:
        self._scroll_jobs_panel()

        html = self.page.content()
        soup = BeautifulSoup(html, "lxml")

        results = self._parse_search_cards(soup, name, scraped_at)
        if results:
            return results

        return self._parse_job_cards(soup, name, scraped_at)

    def _scroll_jobs_panel(self):
        """Scroll the jobs list panel (or whole page) to load all results."""
        try:
            for _ in range(6):
                self.page.evaluate("""
                    const panel = document.querySelector(
                        '.jobs-search-results-list, '  +
                        '.scaffold-layout__list, '     +
                        'ul.jobs-search__results-list'
                    );
                    if (panel) panel.scrollBy(0, 800);
                    else window.scrollBy(0, 800);
                """)
                time.sleep(1)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Parse job cards on the /jobs/search/ results page
    # ------------------------------------------------------------------
    def _parse_search_cards(self, soup: BeautifulSoup,
                             name: str, scraped_at: str) -> list:
        jobs = []

        cards = (
            soup.select("li.jobs-search-results__list-item") or
            soup.select("ul.jobs-search__results-list > li") or
            soup.select("div.job-card-container") or
            soup.select("li.occludable-update")
        )

        print(f"  🔍 Search-page cards found: {len(cards)}")

        for card in cards:
            job = self._extract_from_card(card, name, scraped_at)
            if job and job["Job_Title"] not in ("N/A", ""):
                jobs.append(job)

        return jobs

    # ------------------------------------------------------------------
    # Parse job cards on a company /jobs/ page (carousel / grid)
    # ------------------------------------------------------------------
    def _parse_job_cards(self, soup: BeautifulSoup,
                          name: str, scraped_at: str) -> list:
        jobs = []

        cards = (
            soup.select("div.job-card-container") or
            soup.select("li.jobs-search-results__list-item") or
            soup.select("ul.jobs-search__results-list > li") or
            []
        )

        print(f"  🔍 Company-page cards found: {len(cards)}")

        for card in cards:
            job = self._extract_from_card(card, name, scraped_at)
            if job and job["Job_Title"] not in ("N/A", ""):
                jobs.append(job)

        return jobs

    # ------------------------------------------------------------------
    # Extract all fields from a single job card (BeautifulSoup Tag)
    # ------------------------------------------------------------------
    def _extract_from_card(self, card, name: str, scraped_at: str) -> dict:

        # ── Job Title ──────────────────────────────────────────────────
        title = "N/A"
        for sel in [
            "a.job-card-list__title",
            "a.job-card-container__link",
            ".job-card-list__title--link",
            "h3.base-search-card__title",
            "h3",
            "a[href*='/jobs/view/']",
        ]:
            el = card.select_one(sel)
            if el:
                title = el.get_text(separator=" ", strip=True)
                if title:
                    break

        # ── Job Link ───────────────────────────────────────────────────
        job_link = "N/A"
        for sel in [
            "a.job-card-list__title",
            "a.job-card-container__link",
            "a[href*='/jobs/view/']",
            "a[href*='currentJobId']",
        ]:
            el = card.select_one(sel)
            if el and el.get("href"):
                href = el["href"]
                if href.startswith("/"):
                    href = "https://www.linkedin.com" + href
                job_link = href.split("?")[0]
                break

        # ── Location ───────────────────────────────────────────────────
        location = "N/A"

        # Pass 1: try dedicated location selectors first
        for sel in [
            "span.job-search-card__location",
            ".job-card-container__metadata-item--location",
            "li.job-card-container__metadata-item",
            ".artdeco-entity-lockup__caption li",
            ".base-search-card__metadata span",
            "span.tvm__text--neutral",
        ]:
            el = card.select_one(sel)
            if el:
                text = el.get_text(" ", strip=True)
                if _is_location(text):
                    location = text
                    break

        # Pass 2: scan ALL metadata items if Pass 1 found nothing
        if location == "N/A":
            for sel in [
                ".job-card-container__metadata-item",
                ".job-card-list__footer-wrapper li",
                ".base-search-card__metadata li",
                ".artdeco-entity-lockup__caption li",
            ]:
                for el in card.select(sel):
                    text = el.get_text(" ", strip=True)
                    if _is_location(text):
                        location = text
                        break
                if location != "N/A":
                    break

        # ── Salary ─────────────────────────────────────────────────────
        salary = "N/A"
        card_text = card.get_text(separator="\n")
        m = re.search(
            r'(\$[\d,]+(?:\.\d+)?(?:K)?(?:/(?:yr|hr|mo|year|hour|month))?'
            r'(?:\s*[-–]\s*\$[\d,]+(?:\.\d+)?(?:K)?(?:/(?:yr|hr|mo|year|hour|month))?)?)',
            card_text, re.I
        )
        if m:
            salary = m.group(1).strip()
        else:
            for sel in [
                ".job-card-container__salary-info",
                "span[class*='salary']",
                "div[class*='salary']",
            ]:
                el = card.select_one(sel)
                if el:
                    salary = el.get_text(strip=True)
                    break

        # ── Job Type ───────────────────────────────────────────────────
        job_type = "N/A"
        for pattern in [
            r'\b(Full[- ]time|Part[- ]time|Contract|Internship|'
            r'Temporary|Volunteer|Other)\b',
        ]:
            m = re.search(pattern, card_text, re.I)
            if m:
                job_type = m.group(1)
                break

        work_mode = "N/A"
        for pattern in [r'\b(On[- ]?site|Remote|Hybrid)\b']:
            m = re.search(pattern, card_text, re.I)
            if m:
                work_mode = m.group(1)
                break
        if job_type == "N/A" and work_mode != "N/A":
            job_type = work_mode
        elif work_mode != "N/A":
            job_type = f"{job_type} · {work_mode}"

        # ── Posted Date ────────────────────────────────────────────────
        posted_date = "N/A"
        time_el = card.select_one("time")
        if time_el:
            posted_date = (
                time_el.get("datetime") or
                time_el.get_text(strip=True) or
                "N/A"
            )
        if posted_date == "N/A":
            m = re.search(
                r'(\d+\s+(?:minute|hour|day|week|month|year)s?\s+ago'
                r'|Just now|Today)',
                card_text, re.I
            )
            if m:
                posted_date = m.group(1)
        if posted_date == "N/A":
            for sel in [
                ".job-card-container__listed-time",
                "time.job-search-card__listdate",
                "span[class*='date']",
                "span[class*='time']",
            ]:
                el = card.select_one(sel)
                if el:
                    posted_date = (
                        el.get("datetime") or
                        el.get_text(strip=True) or
                        "N/A"
                    )
                    if posted_date != "N/A":
                        break

        if title == "N/A":
            return None

        return {
            "Company":     name,
            "Job_Title":   title,
            "Location":    location,
            "Salary":      salary,
            "Job_Type":    job_type,
            "Posted_Date": posted_date,
            "Job_Link":    job_link,
            "Scraped_At":  scraped_at,
        }