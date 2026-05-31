from playwright.sync_api import sync_playwright
import pandas as pd
import time
import re
from datetime import datetime

GOTO_TIMEOUT = 60_000

VALID_CATEGORIES = [
    "Where they live",
    "Where they studied",
    "What they studied",
    "What they are skilled at",
    "What they do",
    "How they got there",
]

JUNK = {
    "add", "+ add", "show more", "see more", "follow", "connect",
    "message", "search employees by title, keyword or school",
    "people you may know", "cards updated", "associated members",
}

CLASS_TO_CATEGORY = {
    "geo-region":       "Where they live",
    "organization":     "Where they studied",
    "field-of-study":   "What they studied",
    "skill":            "What they are skilled at",
    "current-function": "What they do",
    "degree":           "How they got there",
}


def parse_entries(lines: list) -> list:
    results = []
    seen    = set()
    i       = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line or line.lower() in JUNK or line in VALID_CATEGORIES:
            i += 1
            continue
        m = re.match(r"^([\d,]+)\s*\|\s*(.+)$", line)
        if m:
            count = m.group(1).replace(",", "")
            label = m.group(2).strip()
            if label and label.lower() not in JUNK and label not in seen:
                results.append({"count": count, "label": label})
                seen.add(label)
            i += 1
            continue
        if re.match(r"^[\d,]+$", line):
            count = line.replace(",", "")
            label = None
            for offset in range(1, 4):
                if i + offset >= len(lines):
                    break
                cand = lines[i + offset].strip()
                if not cand:
                    continue
                if re.match(r"^[\d,]+$", cand):
                    break
                if cand.lower() in JUNK or cand in VALID_CATEGORIES:
                    break
                label = cand
                i += offset + 1
                break
            else:
                i += 1
                continue
            if label and label not in seen:
                results.append({"count": count, "label": label})
                seen.add(label)
            if label is None:
                i += 1
            continue
        i += 1
    return results


class LinkedInScraper:

    def __init__(self, email, password):
        self.email    = email
        self.password = password
        self.pw       = None
        self.context  = None
        self.page     = None
        self.posts    = []
        self.people   = []

    def start(self):
        print("🚀 Starting browser...")
        self.pw = sync_playwright().start()
        self.context = self.pw.chromium.launch_persistent_context(
            user_data_dir = "linkedin_profile",
            headless      = False,
            viewport      = {"width": 1440, "height": 900},
            args          = ["--disable-blink-features=AutomationControlled"],
        )
        self.page = self.context.new_page()
        print("✅ Browser ready")

    def stop(self):
        try:
            self.context.close()
            self.pw.stop()
        except:
            pass

    def goto(self, url, retries=3):
        for attempt in range(retries):
            try:
                print(f"🌐 {url}")
                self.page.goto(url, timeout=GOTO_TIMEOUT, wait_until="commit")
                time.sleep(5)
                return
            except Exception as e:
                print(f"  Retry {attempt+1}: {e}")
                time.sleep(5)
        raise Exception(f"Failed: {url}")

    def scroll_to_bottom(self):
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

    def login(self):
        self.goto("https://www.linkedin.com/login")
        try:
            self.page.locator('input[name="session_key"]').fill(self.email)
            self.page.locator('input[name="session_password"]').fill(self.password)
            self.page.locator('button[type="submit"]').click()
            self.page.wait_for_url("**/feed/**", timeout=120_000)
            print("✅ Logged in")
        except:
            print("⚠  Manual login required — complete it in the browser window")
            self.page.wait_for_url("**/feed/**", timeout=300_000)
            print("✅ Manual login detected")

    def get_likes(self, post) -> str:
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

    # ── FIX 1: extract post text including video posts ──────────────────────
    def _extract_post_text(self, post) -> str:
        """
        Try every known LinkedIn text container in priority order.
        Video posts render text in a commentary/description span that the
        original code missed.
        """
        selectors = [
            # Standard text post
            "div.update-components-text",
            # Video post description overlay
            "div.update-components-video__commentary",
            # Reshared post text
            "div.update-components-update-v2__commentary",
            # Article / document share
            "span.break-words",
            # Generic fallback
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

        # Last resort: pull all visible text from the post container,
        # strip navigation/button noise, and return whatever is left.
        try:
            raw = post.inner_text(timeout=3000)
            lines = [l.strip() for l in raw.splitlines() if l.strip()]
            # Drop lines that look like UI chrome (short button labels, counts)
            clean = [l for l in lines if len(l) > 15 and not re.match(r"^[\d,]+$", l)]
            if clean:
                return re.sub(r"\s+", " ", " ".join(clean[:8])).strip()
        except:
            pass
        return ""

    def scrape_posts(self, slug, name):
        print(f"\n📱 Posts: {name}")
        self.goto(f"https://www.linkedin.com/company/{slug}/posts/?feedView=all")
        print("  Scrolling to load all posts...")
        self.scroll_to_bottom()

        all_posts = self.page.locator("div.feed-shared-update-v2").all()
        print(f"  Total posts found: {len(all_posts)}")

        for i, post in enumerate(all_posts):
            try:
                # Expand "see more" if present
                try:
                    see_more = post.locator(
                        "button.feed-shared-inline-show-more-text__see-more-less-toggle"
                    )
                    if see_more.count() > 0:
                        see_more.first.click(timeout=2000)
                        time.sleep(1)
                except:
                    pass

                # ── Use improved extractor ──
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

                likes = self.get_likes(post)

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

                self.posts.append({
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

    # ══════════════════════════════════════════════════════════════════
    # PEOPLE — complete rewrite of the card-reading logic
    # ══════════════════════════════════════════════════════════════════

    def _get_active_slide_index(self) -> int:
        try:
            dots = self.page.locator(
                "ol.artdeco-carousel__indicator-list button"
            ).all()
            for idx, dot in enumerate(dots):
                cls  = dot.get_attribute("class") or ""
                asel = dot.get_attribute("aria-selected") or ""
                cur  = dot.get_attribute("aria-current") or ""
                if "active" in cls or asel == "true" or cur == "true":
                    return idx
        except:
            pass
        return 0

    def _total_dots(self) -> int:
        try:
            return len(self.page.locator(
                "ol.artdeco-carousel__indicator-list button"
            ).all())
        except:
            return 0

    def _scroll_card_into_view(self, card_locator):
        try:
            card_locator.scroll_into_view_if_needed(timeout=3000)
            time.sleep(1)
        except:
            pass

    # ── FIX 2: robust card reader that handles geo-region / organization ──
    def _read_active_cards(self) -> dict:
        collected = {}
        active_idx = self._get_active_slide_index()

        active_item = None
        try:
            items = self.page.locator("li.artdeco-carousel__item").all()
            if items and active_idx < len(items):
                active_item = items[active_idx]
        except:
            pass

        card_parent = active_item if active_item else self.page

        # ── Broader card discovery: include every bar-graph suffix ──
        card_selectors = [
            "div[class*='org-people-bar-graph-module__geo-region']",
            "div[class*='org-people-bar-graph-module__organization']",
            "div[class*='org-people-bar-graph-module__current-function']",
            "div[class*='org-people-bar-graph-module__degree']",
            "div[class*='org-people-bar-graph-module__field-of-study']",
            "div[class*='org-people-bar-graph-module__skill']",
            # Sometimes LinkedIn uses a generic insight-container wrapper
            "div.insight-container",
            # Newer layout fallback
            "div[class*='org-people-insights-module']",
        ]

        found_cards = []
        seen_ids = set()

        for sel in card_selectors:
            try:
                cards = card_parent.locator(sel).all()
                for card in cards:
                    cid = ""
                    try:
                        cid = card.get_attribute("id") or ""
                    except:
                        pass
                    # Deduplicate by id when available
                    if cid and cid in seen_ids:
                        continue
                    if cid:
                        seen_ids.add(cid)
                    found_cards.append(card)
            except:
                pass

        for card in found_cards:
            self._scroll_card_into_view(card)

            # ── Category detection (same 3 methods as before) ──
            category = None
            try:
                title_el = card.locator("div.insight-container__title").first
                raw = title_el.inner_text(timeout=2000).strip()
                for line in raw.splitlines():
                    line = line.strip()
                    if line in VALID_CATEGORIES:
                        category = line
                        break
                if not category:
                    for vc in VALID_CATEGORIES:
                        if vc.lower() in raw.lower():
                            category = vc
                            break
            except:
                pass

            if not category:
                try:
                    cls = card.get_attribute("class") or ""
                    for suffix, cat in CLASS_TO_CATEGORY.items():
                        if suffix in cls:
                            category = cat
                            break
                except:
                    pass

            if not category:
                try:
                    raw = card.inner_text(timeout=2000)
                    for line in raw.splitlines():
                        line = line.strip()
                        if line in VALID_CATEGORIES:
                            category = line
                            break
                except:
                    pass

            if not category:
                continue

            # ── Entry extraction — Method A: button elements ──
            entries = []
            seen_labels = set()

            # FIX: also try aria-label on the bar elements themselves
            btn_selectors = [
                "button[class*='org-people-bar-graph-element']",
                "li[class*='org-people-bar-graph-element']",   # some layouts use <li>
                "div[class*='org-people-bar-graph-element']",
            ]

            for btn_sel in btn_selectors:
                try:
                    buttons = card.locator(btn_sel).all()
                    for btn in buttons:
                        raw_text = ""
                        try:
                            handle = btn.element_handle(timeout=1000)
                            if handle:
                                raw_text = self.page.evaluate(
                                    """el => {
                                        const aria = el.getAttribute('aria-label') || '';
                                        const inner = el.innerText || '';
                                        const content = el.textContent || '';
                                        return aria || inner || content;
                                    }""",
                                    handle
                                ) or ""
                        except:
                            pass

                        if not raw_text:
                            try:
                                raw_text = btn.inner_text(timeout=500) or ""
                            except:
                                raw_text = ""

                        raw_text = raw_text.strip()
                        if not raw_text:
                            continue

                        count = label = None

                        m = re.match(r"^([\d,]+)\s*\|\s*(.+)$", raw_text)
                        if m:
                            count = m.group(1).replace(",", "")
                            label = m.group(2).strip()
                        else:
                            parts = [p.strip() for p in raw_text.splitlines()
                                     if p.strip()]
                            if len(parts) >= 2 and re.match(r"^[\d,]+$", parts[0]):
                                count = parts[0].replace(",", "")
                                label = parts[1]
                            else:
                                m2 = re.match(r"^([\d,]+)\s+(.+)$", raw_text)
                                if m2:
                                    count = m2.group(1).replace(",", "")
                                    label = m2.group(2).strip()

                        if count and label:
                            label = label.strip()
                            if (label.lower() not in JUNK
                                    and label not in VALID_CATEGORIES
                                    and label not in seen_labels):
                                entries.append({"count": count, "label": label})
                                seen_labels.add(label)
                    if entries:
                        break   # found entries with this selector, no need to try others
                except:
                    pass

            # ── Method B: full card innerText fallback ──
            if not entries:
                try:
                    raw = card.inner_text(timeout=3000)
                    entries = parse_entries(raw.splitlines())
                except:
                    pass

            # ── Method C: page.evaluate on the whole card ──
            if not entries:
                try:
                    handle = card.element_handle(timeout=1000)
                    if handle:
                        raw = self.page.evaluate(
                            "el => el.innerText || el.textContent || ''",
                            handle
                        )
                        entries = parse_entries(raw.splitlines())
                except:
                    pass

            # ── FIX 3: BeautifulSoup deep parse as final fallback ──
            # Handles cases where Playwright text nodes are still empty
            if not entries:
                try:
                    from bs4 import BeautifulSoup
                    handle = card.element_handle(timeout=1000)
                    if handle:
                        html = self.page.evaluate(
                            "el => el.outerHTML", handle
                        )
                        soup = BeautifulSoup(html, "lxml")
                        text = soup.get_text(separator="\n")
                        entries = parse_entries(text.splitlines())
                except:
                    pass

            if not entries:
                continue

            if category not in collected:
                collected[category] = []
            for e in entries:
                exists = any(x["label"] == e["label"]
                             for x in collected[category])
                if not exists:
                    collected[category].append(e)

        return collected

    def next_slide(self) -> bool:
        for sel in [
            'button[aria-label="Next"]',
            'button.artdeco-carousel__next-button',
            'button[aria-label="Next slide"]',
        ]:
            try:
                for btn in self.page.locator(sel).all():
                    if not btn.is_visible():
                        continue
                    if btn.get_attribute("disabled") is not None:
                        return False
                    if btn.get_attribute("aria-disabled") == "true":
                        return False
                    btn.click(timeout=3000)
                    time.sleep(3)
                    return True
            except:
                pass
        try:
            dots = self.page.locator(
                "ol.artdeco-carousel__indicator-list button"
            ).all()
            for idx, dot in enumerate(dots):
                cls = dot.get_attribute("class") or ""
                sel = dot.get_attribute("aria-selected") or ""
                cur = dot.get_attribute("aria-current") or ""
                if "active" in cls or sel == "true" or cur == "true":
                    if idx + 1 >= len(dots):
                        return False
                    dots[idx + 1].click()
                    time.sleep(3)
                    return True
        except:
            pass
        return False

    def scrape_people(self, slug, name):
        print(f"\n👥 People: {name}")
        self.goto(f"https://www.linkedin.com/company/{slug}/people/")
        time.sleep(5)

        self.page.mouse.wheel(0, 800)
        time.sleep(2)
        self.page.mouse.wheel(0, 800)
        time.sleep(2)

        total = "N/A"
        try:
            body = self.page.locator("body").inner_text(timeout=5000)
            m = re.search(r"([\d,]+)\s+associated members", body)
            if m:
                total = m.group(1)
        except:
            pass
        print(f"  📊 Total members: {total}")

        all_collected: dict = {}
        total_dots = self._total_dots()
        max_slides  = max(total_dots, 6) if total_dots > 0 else 6

        for slide in range(max_slides):
            print(f"  ➡  Slide {slide + 1}")

            slide_data = self._read_active_cards()

            if slide_data:
                for category, entries in slide_data.items():
                    if category not in all_collected:
                        all_collected[category] = []
                    new = 0
                    for e in entries:
                        exists = any(x["label"] == e["label"]
                                     for x in all_collected[category])
                        if not exists:
                            all_collected[category].append(e)
                            new += 1
                            print(f"       {str(e['count']):>8} | {e['label']}")
                    if new:
                        print(f"    ✅ {category}: +{new} "
                              f"(total {len(all_collected[category])})")
            else:
                print("    ⚠  No data on this slide")

            active_idx = self._get_active_slide_index()
            n_dots     = self._total_dots()
            if n_dots > 0 and active_idx >= n_dots - 1:
                print(f"    🛑 Last dot ({active_idx+1}/{n_dots}) — done")
                break

            moved = self.next_slide()
            if not moved:
                print("    🛑 No more slides")
                break

        added = 0
        for category, entries in all_collected.items():
            for rank, e in enumerate(entries, start=1):
                self.people.append({
                    "Company":       name,
                    "Total_Members": total,
                    "Category":      category,
                    "Rank":          rank,
                    "Count":         e["count"],
                    "Label":         e["label"],
                    "Scraped_At":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })
                added += 1

        print(f"  ✅ People rows added: {added}")

    def save(self):
        print("\n💾 Saving to Excel...")
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename  = f"linkedin_data_{timestamp}.xlsx"

        with pd.ExcelWriter(filename, engine="openpyxl") as writer:

            if self.posts:
                df_posts = pd.DataFrame(self.posts)
                df_posts.to_excel(writer, sheet_name="Posts", index=False)
                ws = writer.sheets["Posts"]
                for col in ws.columns:
                    max_len = max(
                        (len(str(cell.value)) for cell in col if cell.value),
                        default=10
                    )
                    ws.column_dimensions[col[0].column_letter].width = min(
                        max_len + 2, 80
                    )
                print(f"✅ Posts sheet: {len(self.posts)} rows")
            else:
                print("⚠  No posts scraped")

            if self.people:
                df_people = pd.DataFrame(self.people)
                df_people.to_excel(writer, sheet_name="People", index=False)
                ws = writer.sheets["People"]
                for col in ws.columns:
                    max_len = max(
                        (len(str(cell.value)) for cell in col if cell.value),
                        default=10
                    )
                    ws.column_dimensions[col[0].column_letter].width = min(
                        max_len + 2, 60
                    )
                print(f"✅ People sheet: {len(self.people)} rows")
                print(f"\n  {'Company':30} | {'Category':28} | "
                      f"{'Rank':4} | {'Count':8} | Label")
                print(f"  {'-'*95}")
                for r in self.people[:30]:
                    print(f"  {r['Company']:30} | {r['Category']:28} | "
                          f"{str(r['Rank']):4} | {str(r['Count']):8} | "
                          f"{r['Label']}")
            else:
                print("⚠  No people data scraped")

        print(f"\n📁 Saved: {filename}")

    def run(self, companies):
        self.start()
        try:
            self.login()
            for co in companies:
                self.scrape_posts(co["slug"], co["display"])
                self.scrape_people(co["slug"], co["display"])
            self.save()
        finally:
            self.stop()


if __name__ == "__main__":

    EMAIL    = "YOUR_EMAIL"
    PASSWORD = "YOUR_PASSWORD"

    COMPANIES = [
        {"slug": "luel",                                    "display": "Luel"},
        {"slug": "galactic-resource-utilization-space-inc", "display": "Galactic Resource Utilization"},
        {"slug": "overdrive-health",                        "display": "Overdrive Health"},
        {"slug": "voxel-energy",                            "display": "Voxel Energy"},
        {"slug": "beyond-reach-labs-inc",                   "display": "Beyond Reach Labs"},
        {"slug": "traverse-so",                             "display": "Traverse"},
    ]

    LinkedInScraper(EMAIL, PASSWORD).run(COMPANIES)
