import re
import time
from datetime import datetime
from utils import JUNK


class PostsScraper:

    def __init__(self, browser):
        self.browser = browser
        self.page    = browser.page

    def _scroll_to_bottom(self):
        prev_count = 0
        no_change_rounds = 0
        while True:
            self.page.mouse.wheel(0, 5000)
            time.sleep(3)
            current = len(self.page.locator("div.feed-shared-update-v2").all())
            print(f"    posts visible: {current}")
            if current == prev_count:
                no_change_rounds += 1
                if no_change_rounds >= 3:
                    break
            else:
                no_change_rounds = 0
            prev_count = current

    def _get_likes(self, post) -> str:
        for sel in [
            'button[aria-label*="reaction"]',
            'button[aria-label*="like"]',
            'span[aria-label*="reaction"]',
        ]:
            try:
                for el in post.locator(sel).all():
                    lbl = el.get_attribute("aria-label") or ""
                    m = re.search(r"([\d,]+)", lbl)
                    if m:
                        return m.group(1).replace(",", "")
            except:
                pass
        for sel in ['span[class*="social-counts"]', 'span[class*="reactions-count"]',
                    'span[class*="likes-count"]', 'span.v-align-middle']:
            try:
                for el in post.locator(sel).all():
                    txt = el.inner_text(timeout=500).strip()
                    if re.match(r"^[\d,]+$", txt):
                        return txt.replace(",", "")
            except:
                pass
        try:
            full = post.inner_text(timeout=3000)
            for pat in [r"([\d,]+)\s*reactions?", r"([\d,]+)\s*likes?"]:
                m = re.search(pat, full, re.I)
                if m:
                    return m.group(1).replace(",", "")
        except:
            pass
        return "0"

    def _extract_post_text(self, post) -> str:
        selectors = [
            "div.update-components-text",
            "div.update-components-video__commentary",
            "div.update-components-update-v2__commentary",
            "span.break-words",
            "div[class*='commentary']",
            "span[class*='commentary']",
            "div[class*='update-components-text']",
        ]
        for sel in selectors:
            try:
                els = post.locator(sel).all()
                for el in els:
                    txt = re.sub(r"\s+", " ", el.inner_text(timeout=2000)).strip()
                    if txt:
                        return txt
            except:
                pass
        try:
            raw = post.inner_text(timeout=3000)
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            clean = [l for l in lines if len(l) > 15 and not re.match(r"^[\d,]+$", l)]
            if clean:
                return re.sub(r"\s+", " ", " ".join(clean[:8])).strip()
        except:
            pass
        return ""

    def scrape(self, slug, name) -> list:
        print(f"\n📱 Posts: {name}")
        self.browser.goto(
            f"https://www.linkedin.com/company/{slug}/posts/?feedView=all"
        )
        print("  Scrolling to load all posts...")
        self._scroll_to_bottom()

        all_posts = self.page.locator("div.feed-shared-update-v2").all()
        print(f"  Total posts found: {len(all_posts)}")

        rows = []
        for i, post in enumerate(all_posts):
            try:
                try:
                    see_more = post.locator(
                        "button.feed-shared-inline-show-more-text__see-more-less-toggle"
                    )
                    if see_more.count() > 0:
                        see_more.first.click(timeout=2000)
                        time.sleep(1)
                except:
                    pass

                text = self._extract_post_text(post)

                link = "N/A"
                try:
                    urn = post.get_attribute("data-urn")
                    if urn:
                        link = (f"https://www.linkedin.com/feed/update/"
                                f"urn:li:activity:{urn.split(':')[-1]}/")
                except:
                    pass

                ext_links = []
                try:
                    for a in post.locator("a").all():
                        href = a.get_attribute("href") or ""
                        if href.startswith("http") and "linkedin.com" not in href:
                            ext_links.append(href)
                    ext_links = list(set(ext_links))
                except:
                    pass

                likes = self._get_likes(post)

                full = ""
                try:
                    full = re.sub(r"\s+", " ",
                                  post.inner_text(timeout=3000)).strip()
                except:
                    pass

                def metric(pat):
                    mm = re.search(pat, full, re.I)
                    return mm.group(1).replace(",", "") if mm else "0"

                comments = metric(r"([\d,]+)\s*comments?")
                reposts  = metric(r"([\d,]+)\s*reposts?")

                date_val = "N/A"
                mm = re.search(r"(\d+\s*[hdwmy])", full)
                if mm:
                    date_val = mm.group(1)

                rows.append({
                    "Company":        name,
                    "Post_Number":    i + 1,
                    "Post_Text":      text,
                    "Post_Link":      link,
                    "External_Links": " | ".join(ext_links),
                    "Likes":          likes,
                    "Comments":       comments,
                    "Reposts":        reposts,
                    "Post_Date":      date_val,
                    "Scraped_At":     datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                print(f"  ✅ Post {i+1}: likes={likes} comments={comments} "
                      f"text_len={len(text)}")
            except Exception as e:
                print(f"  ❌ Post {i+1}: {e}")

        return rows