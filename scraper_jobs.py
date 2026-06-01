import re
import time
from datetime import datetime


class JobsScraper:

    def __init__(self, browser):
        self.browser = browser
        self.page    = browser.page

    def scrape(self, slug, name) -> list:
        print(f"\n💼 Jobs: {name}")
        self.browser.goto(f"https://www.linkedin.com/company/{slug}/jobs/")
        time.sleep(3)

        for _ in range(2):
            self.page.mouse.wheel(0, 800)
            time.sleep(2)

        scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = []

        # Check if no jobs
        try:
            body = self.page.locator("body").inner_text(timeout=5000)
            if "no jobs right now" in body.lower():
                print(f"  ℹ️  No jobs posted for {name}")
                rows.append({
                    "Company":       name,
                    "Job_Title":     "No jobs posted",
                    "Location":      "N/A",
                    "Job_Link":      "N/A",
                    "Posted_Date":   "N/A",
                    "Scraped_At":    scraped_at,
                })
                return rows
        except:
            pass

        # Scrape job cards
        job_selectors = [
            "div.job-card-container",
            "li.jobs-search-results__list-item",
            "div[class*='job-card']",
            "a[class*='job-card']",
        ]

        job_cards = []
        for sel in job_selectors:
            try:
                cards = self.page.locator(sel).all()
                if cards:
                    job_cards = cards
                    break
            except:
                pass

        print(f"  Found {len(job_cards)} job(s)")

        for i, card in enumerate(job_cards):
            try:
                title = "N/A"
                for sel in [
                    "span[class*='job-card-list__title']",
                    "a[class*='job-card-list__title']",
                    "h3",
                    "strong",
                ]:
                    try:
                        txt = card.locator(sel).first.inner_text(timeout=1000).strip()
                        if txt:
                            title = txt
                            break
                    except:
                        pass

                location = "N/A"
                for sel in [
                    "li[class*='job-card-container__metadata-item']",
                    "span[class*='job-card-container__metadata-item']",
                ]:
                    try:
                        txt = card.locator(sel).first.inner_text(timeout=1000).strip()
                        if txt:
                            location = txt
                            break
                    except:
                        pass

                job_link = "N/A"
                try:
                    for a in card.locator("a").all():
                        href = a.get_attribute("href") or ""
                        if "/jobs/view/" in href:
                            job_link = href.split("?")[0]
                            break
                except:
                    pass

                posted = "N/A"
                try:
                    full = card.inner_text(timeout=2000)
                    m = re.search(r"(\d+\s*(?:hour|day|week|month)s?\s*ago)", full, re.I)
                    if m:
                        posted = m.group(1)
                except:
                    pass

                rows.append({
                    "Company":     name,
                    "Job_Title":   title,
                    "Location":    location,
                    "Job_Link":    job_link,
                    "Posted_Date": posted,
                    "Scraped_At":  scraped_at,
                })
                print(f"  ✅ Job {i+1}: {title} | {location}")

            except Exception as e:
                print(f"  ❌ Job {i+1}: {e}")

        if not rows:
            rows.append({
                "Company":     name,
                "Job_Title":   "No jobs found",
                "Location":    "N/A",
                "Job_Link":    "N/A",
                "Posted_Date": "N/A",
                "Scraped_At":  scraped_at,
            })

        return rows