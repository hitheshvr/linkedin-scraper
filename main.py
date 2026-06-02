import json
import pandas as pd
from datetime import datetime

from config import EMAIL, PASSWORD, COMPANIES
from browser import Browser
from scraper_posts import PostsScraper
from scraper_people import PeopleScraper
from scraper_about import AboutScraper
from scraper_jobs import JobsScraper


def save_to_excel(all_posts, all_people, all_members, all_about, all_jobs):
    print("\n💾 Saving to Excel...")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename  = f"linkedin_data_{timestamp}.xlsx"

    def write_sheet(writer, data, sheet_name, max_width=80):
        if not data:
            print(f"⚠  No data for sheet: {sheet_name}")
            return
        df = pd.DataFrame(data)
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        ws = writer.sheets[sheet_name]
        for col in ws.columns:
            max_len = max(
                (len(str(cell.value)) for cell in col if cell.value),
                default=10
            )
            ws.column_dimensions[col[0].column_letter].width = min(
                max_len + 2, max_width
            )
        print(f"✅ Sheet '{sheet_name}': {len(data)} rows")

    with pd.ExcelWriter(filename, engine="openpyxl") as writer:
        write_sheet(writer, all_posts,    "Posts",          max_width=80)
        write_sheet(writer, all_people,   "People",         max_width=60)
        write_sheet(writer, all_members,  "People_Members", max_width=80)
        write_sheet(writer, all_about,    "About",          max_width=80)
        write_sheet(writer, all_jobs,     "Jobs",           max_width=80)

    print(f"📁 Excel saved: {filename}")
    return filename


def save_to_json(all_posts, all_people, all_members, all_about, all_jobs, timestamp):
    """Save all data as a single structured JSON file."""
    print("\n💾 Saving to JSON...")
    filename = f"linkedin_data_{timestamp}.json"

    data = {
        "scraped_at": timestamp,
        "posts":          all_posts,
        "people_stats":   all_people,
        "people_members": all_members,
        "about":          all_about,
        "jobs":           all_jobs,
    }

    with open(filename, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"📁 JSON saved: {filename}")


def main():
    browser = Browser()
    browser.start()

    posts_scraper  = PostsScraper(browser)
    people_scraper = PeopleScraper(browser)
    about_scraper  = AboutScraper(browser)
    jobs_scraper   = JobsScraper(browser)

    all_posts   = []
    all_people  = []
    all_members = []
    all_about   = []
    all_jobs    = []

    try:
        browser.login(EMAIL, PASSWORD)

        for co in COMPANIES:
            slug = co["slug"]
            name = co["display"]

            all_about += about_scraper.scrape(slug, name)
            all_posts += posts_scraper.scrape(slug, name)

            stats_rows, member_rows = people_scraper.scrape(slug, name)
            all_people  += stats_rows
            all_members += member_rows

            all_jobs += jobs_scraper.scrape(slug, name)

        # Use same timestamp for both files so they match
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_to_excel(all_posts, all_people, all_members, all_about, all_jobs)
        save_to_json(all_posts, all_people, all_members, all_about, all_jobs,
                     timestamp)

    finally:
        browser.stop()


if __name__ == "__main__":
    main()