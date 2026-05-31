
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


# ══════════════════════════════════════════════════════════════════════
# CORE PARSER
# ══════════════════════════════════════════════════════════════════════

def parse_entries(lines: list) -> list:
    """
    Extract [{count, label}] from a card's text lines.

    Three formats LinkedIn uses:
      A  "107,854 | United States"        — pipe on same line
      B  "107,854\\nUnited States"         — label on very next line
      C  "107,854\\n\\nUnited States"       — blank (progress bar) in between

    CAUSE 2 fix: after a bare number, scan forward up to 3 lines.
    """
    results = []
    seen    = set()
    i       = 0

    while i < len(lines):
        line = lines[i].strip()

        if not line or line.lower() in JUNK or line in VALID_CATEGORIES:
            i += 1
            continue

        # Format A: "107,854 | United States"
        m = re.match(r"^([\d,]+)\s*\|\s*(.+)$", line)
        if m:
            count = m.group(1).replace(",", "")
            label = m.group(2).strip()
            if label and label.lower() not in JUNK and label not in seen:
                results.append({"count": count, "label": label})
                seen.add(label)
            i += 1
            continue

        # Format B / C: bare number, then scan ahead for label
        if re.match(r"^[\d,]+$", line):
            count = line.replace(",", "")
            label = None
            for offset in range(1, 4):
                if i + offset >= len(lines):
                    break
                cand = lines[i + offset].strip()
                if not cand:
                    continue                         # blank → keep scanning
                if re.match(r"^[\d,]+$", cand):
                    break                            # another number → stop
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


# ══════════════════════════════════════════════════════════════════════
# SCRAPER
# ══════════════════════════════════════════════════════════════════════

class LinkedInScraper:

    def __init__(self, email, password):
        self.email    = email
        self.password = password
        self.pw       = None
        self.context  = None
        self.page     = None
        self.posts    = []
        self.people   = []

    # ── browser ──────────────────────────────────────────────────────

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

    # ── navigation ────────────────────────────────────────────────────

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

    def scroll(self, times=8):
        for _ in range(times):
            self.page.mouse.wheel(0, 3000)
            time.sleep(2)

    # ── login ─────────────────────────────────────────────────────────

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

    # ── likes (BONUS fix) ─────────────────────────────────────────────
    # LinkedIn puts reaction count in aria-label on a <button>,
    # NOT in inner_text(). That is why Likes was always 0 in old code.

    def get_likes(self, post) -> str:
        # Layer 1: aria-label on reaction button (most reliable)
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

        # Layer 2: social count span
        for sel in ['span[class*="social-counts"]', 'span[class*="reactions-count"]',
                    'span[class*="likes-count"]', 'span.v-align-middle']:
            try:
                for el in post.locator(sel).all():
                    txt = el.inner_text(timeout=500).strip()
                    if re.match(r"^[\d,]+$", txt):
                        return txt.replace(",", "")
            except:
                pass

        # Layer 3: raw text fallback
        try:
            full = post.inner_text(timeout=3000)
            for pat in [r"([\d,]+)\s*reactions?", r"([\d,]+)\s*likes?"]:
                m = re.search(pat, full, re.I)
                if m:
                    return m.group(1).replace(",", "")
        except:
            pass

        return "0"

    # ── posts ─────────────────────────────────────────────────────────

    def scrape_posts(self, slug, name, max_posts=20):
        print(f"\n📱 Posts: {name}")
        self.goto(f"https://www.linkedin.com/company/{slug}/posts/?feedView=all")
        self.scroll(times=10)

        all_posts = self.page.locator("div.feed-shared-update-v2").all()
        print(f"  Found {len(all_posts)} posts")

        for i, post in enumerate(all_posts[:max_posts]):
            try:
                text = ""
                try:
                    text = re.sub(r"\s+", " ",
                        post.locator("div.update-components-text")
                            .inner_text(timeout=3000)).strip()
                except:
                    pass

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
                    full = re.sub(r"\s+", " ", post.inner_text(timeout=3000)).strip()
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
                print(f"  ✅ Post {i+1}: likes={likes} comments={comments}")

            except Exception as e:
                print(f"  ❌ Post {i+1}: {e}")

    # ── carousel next (CAUSE 3 fix) ───────────────────────────────────

    def next_slide(self) -> bool:
        """
        CAUSE 3 fix: check aria-disabled before clicking.
        LinkedIn keeps the button visible but sets aria-disabled='true'
        on the last slide — old code missed this and looped forever.
        """
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

        # dot indicator fallback
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

    # ── JS card fallback ──────────────────────────────────────────────

    def _js_read_card(self, card) -> list:
        try:
            result = self.page.evaluate("""
                (el) => {
                    const out = [];
                    const seen = new Set();
                    const raw = (el.innerText || '').split('\\n');
                    for (let i = 0; i < raw.length; i++) {
                        const line = raw[i].trim();
                        const mA = line.match(/^([\\d,]+)\\s*\\|\\s*(.+)$/);
                        if (mA) {
                            const label = mA[2].trim();
                            if (!seen.has(label)) {
                                out.push({count: mA[1].replace(/,/g,''), label});
                                seen.add(label);
                            }
                            continue;
                        }
                        if (/^[\\d,]+$/.test(line)) {
                            for (let j = i+1; j <= i+3 && j < raw.length; j++) {
                                const c = raw[j].trim();
                                if (!c) continue;
                                if (/^[\\d,]+$/.test(c)) break;
                                if (!seen.has(c)) {
                                    out.push({count: line.replace(/,/g,''), label: c});
                                    seen.add(c);
                                }
                                break;
                            }
                        }
                    }
                    return out;
                }
            """, card.element_handle())
            return result or []
        except:
            return []

    # ── full-page text fallback ───────────────────────────────────────

    def _fullpage_parse(self) -> dict:
        collected = {}
        try:
            text = self.page.evaluate("() => document.body.innerText")
        except:
            return collected

        lines   = [l.strip() for l in text.split("\n") if l.strip()]
        cur_cat = None

        for i, line in enumerate(lines):
            if line in VALID_CATEGORIES:
                cur_cat = line
                if cur_cat not in collected:
                    collected[cur_cat] = []
                continue
            if not cur_cat:
                continue

            m = re.match(r"^([\d,]+)\s*\|\s*(.+)$", line)
            if m:
                count = m.group(1).replace(",", "")
                label = m.group(2).strip()
                if label and label.lower() not in JUNK:
                    if not any(e["label"] == label for e in collected[cur_cat]):
                        collected[cur_cat].append({"count": count, "label": label})
                continue

            if re.match(r"^[\d,]+$", line):
                for offset in range(1, 4):
                    if i + offset >= len(lines):
                        break
                    cand = lines[i + offset].strip()
                    if not cand:
                        continue
                    if re.match(r"^[\d,]+$", cand) or cand.lower() in JUNK:
                        break
                    if cand in VALID_CATEGORIES:
                        break
                    if not any(e["label"] == cand for e in collected[cur_cat]):
                        collected[cur_cat].append({
                            "count": line.replace(",", ""), "label": cand
                        })
                    break

        return collected

    # ── people (all 3 causes fixed here) ─────────────────────────────

    def scrape_people(self, slug, name):
        print(f"\n👥 People: {name}")
        self.goto(f"https://www.linkedin.com/company/{slug}/people/")
        time.sleep(5)
        self.scroll(times=3)

        total = "N/A"
        try:
            body = self.page.locator("body").inner_text(timeout=5000)
            m = re.search(r"([\d,]+)\s+associated members", body)
            if m:
                total = m.group(1)
        except:
            pass
        print(f"  📊 Total members: {total}")

        seen:      set  = set()
        collected: dict = {}

        for slide in range(12):
            print(f"  ➡ Slide {slide + 1}")

            cards = self.page.locator("div.org-people-bar-graph-module").all()
            if not cards:
                cards = self.page.locator("div.artdeco-card").all()
            print(f"  Found {len(cards)} cards")

            for card in cards:
                try:
                    raw   = card.inner_text(timeout=3000)
                    lines = raw.split("\n")      # keep blank lines for Format C

                    # CAUSE 1 FIX: scan ALL lines for heading
                    category = None
                    for line in lines:
                        if line.strip() in VALID_CATEGORIES:
                            category = line.strip()
                            break
                    if not category:
                        continue

                    # CAUSE 2 FIX: parse_entries looks ahead 1-3 lines
                    entries = parse_entries(lines)
                    if not entries:
                        entries = self._js_read_card(card)
                    if not entries:
                        print(f"  ⚠ No entries for '{category}'")
                        continue

                    print(f"  ✅ {category}: {len(entries)} entries")
                    if category not in collected:
                        collected[category] = []

                    for e in entries:
                        key = (name, category, e["label"])
                        if key in seen:
                            continue
                        seen.add(key)
                        collected[category].append(e)
                        print(f"     {e['count']:>8} | {e['label']}")

                except Exception as ex:
                    print(f"  ❌ Card error: {ex}")

            # CAUSE 3 FIX: use dot indicators to detect last slide
            try:
                dots = self.page.locator(
                    "ol.artdeco-carousel__indicator-list button"
                ).all()
                if dots:
                    for idx, dot in enumerate(dots):
                        cls = dot.get_attribute("class") or ""
                        sel = dot.get_attribute("aria-selected") or ""
                        cur = dot.get_attribute("aria-current") or ""
                        if "active" in cls or sel == "true" or cur == "true":
                            if idx >= len(dots) - 1:
                                print(f"  🛑 Last dot ({idx+1}/{len(dots)}) — done")
                                # break out of the carousel for-loop
                                goto_done = True
                            break
                    else:
                        goto_done = False
                    if goto_done:
                        break
            except:
                pass

            moved = self.next_slide()
            if not moved:
                print("  🛑 No more slides")
                break

        if not collected:
            print("  ⚠ Carousel produced nothing — trying full-page text parse")
            collected = self._fullpage_parse()

        added = 0
        for category, entries in collected.items():
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

    # ── save ──────────────────────────────────────────────────────────

    def save(self):
        print("\n💾 Saving...")

        if self.posts:
            pd.DataFrame(self.posts).to_csv(
                "linkedin_posts.csv", index=False, encoding="utf-8-sig"
            )
            print(f"✅ linkedin_posts.csv ({len(self.posts)} rows)")

        if self.people:
            pd.DataFrame(self.people).to_csv(
                "linkedin_people.csv", index=False, encoding="utf-8-sig"
            )
            print(f"✅ linkedin_people.csv ({len(self.people)} rows)")
            print("\n  Sample (first 20 rows):")
            print(f"  {'Company':15} | {'Category':28} | {'Rank':4} | {'Count':8} | Label")
            print(f"  {'-'*80}")
            for r in self.people[:20]:
                print(f"  {r['Company']:15} | {r['Category']:28} | "
                      f"{str(r['Rank']):4} | {str(r['Count']):8} | {r['Label']}")
        else:
            print("⚠  No people data — check the console output above for clues")

    # ── run ───────────────────────────────────────────────────────────

    def run(self, companies, max_posts=20):
        self.start()
        try:
            self.login()
            for co in companies:
                self.scrape_posts(co["slug"], co["display"], max_posts)
                self.scrape_people(co["slug"], co["display"])
            self.save()
        finally:
            self.stop()


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":

    EMAIL    = "testacc202026@gmail.com"
    PASSWORD = "123test123"

    COMPANIES = [
        {"slug": "google",        "display": "Google"},
        {"slug": "pirislabs",     "display": "Piris Labs"},
        {"slug": "voxel-energy",  "display": "Voxel Energy"},
        {"slug": "axion-orbital", "display": "Axion Orbital"},
    ]

    LinkedInScraper(EMAIL, PASSWORD).run(COMPANIES, max_posts=20)
