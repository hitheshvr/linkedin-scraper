import re
import time
from datetime import datetime


class AboutScraper:

    def __init__(self, browser):
        self.browser = browser
        self.page    = browser.page

    def _safe_text(self, selector) -> str:
        try:
            el = self.page.locator(selector).first
            return el.inner_text(timeout=3000).strip()
        except:
            return ""

    def scrape(self, slug, name) -> list:
        print(f"\nℹ️  About: {name}")
        self.browser.goto(f"https://www.linkedin.com/company/{slug}/about/")
        time.sleep(3)

        # Scroll to load all content
        for _ in range(3):
            self.page.mouse.wheel(0, 800)
            time.sleep(1)

        scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        rows = []

        try:
            body_text = self.page.locator("body").inner_text(timeout=8000)

            def extract(pattern, text=body_text):
                m = re.search(pattern, text, re.I | re.S)
                return m.group(1).strip() if m else "N/A"

            # Overview / tagline
            overview = "N/A"
            try:
                overview_el = self.page.locator(
                    "section.org-page-details-module__card-spacing p, "
                    "p.break-words"
                ).first
                overview = overview_el.inner_text(timeout=3000).strip() or "N/A"
            except:
                pass

            # Website
            website = "N/A"
            try:
                for a in self.page.locator("a[href*='http']").all():
                    href = a.get_attribute("href") or ""
                    if "linkedin.com" not in href and href.startswith("http"):
                        website = href
                        break
            except:
                pass

            # Industry, company size, headquarters, founded, specialties
            industry      = extract(r"Industry\s*\n(.+?)(?:\n|$)")
            company_size  = extract(r"Company size\s*\n(.+?)(?:\n|$)")
            assoc_members = extract(r"([\d,]+)\s+associated members")
            headquarters  = extract(r"Headquarters\s*\n(.+?)(?:\n|$)")
            founded       = extract(r"Founded\s*\n(.+?)(?:\n|$)")
            specialties   = extract(r"Specialties\s*\n(.+?)(?:\n|$)")

            # Followers
            followers = "N/A"
            m = re.search(r"([\d,]+)\s+followers", body_text, re.I)
            if m:
                followers = m.group(1)

            # Locations — scrape all listed addresses
            locations = []
            try:
                loc_items = self.page.locator(
                    "div[class*='org-location'] li, "
                    "ul.org-locations-module__list li, "
                    "div.org-page-details__definition-text"
                ).all()
                for loc in loc_items:
                    txt = loc.inner_text(timeout=2000).strip()
                    if txt and txt not in locations:
                        locations.append(txt)
            except:
                pass

            # Fallback: extract addresses from body text
            if not locations:
                for m in re.finditer(
                    r"(?:Headquarters|Primary|Secondary|Location)\s*\n(.+?)(?:\nGet directions|$)",
                    body_text, re.I
                ):
                    loc = m.group(1).strip()
                    if loc and loc not in locations:
                        locations.append(loc)

            rows.append({
                "Company":          name,
                "Overview":         overview,
                "Website":          website,
                "Industry":         industry,
                "Company_Size":     company_size,
                "Associated_Members": assoc_members,
                "Followers":        followers,
                "Headquarters":     headquarters,
                "Founded":          founded,
                "Specialties":      specialties,
                "Locations":        " | ".join(locations) if locations else "N/A",
                "Scraped_At":       scraped_at,
            })

            print(f"  ✅ About scraped: {name} | {industry} | {headquarters}")

        except Exception as e:
            print(f"  ❌ About failed for {name}: {e}")
            rows.append({
                "Company":          name,
                "Overview":         "N/A",
                "Website":          "N/A",
                "Industry":         "N/A",
                "Company_Size":     "N/A",
                "Associated_Members": "N/A",
                "Followers":        "N/A",
                "Headquarters":     "N/A",
                "Founded":          "N/A",
                "Specialties":      "N/A",
                "Locations":        "N/A",
                "Scraped_At":       scraped_at,
            })

        return rows