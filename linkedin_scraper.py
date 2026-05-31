
from playwright.sync_api import sync_playwright, Page
import csv
import time
import re
from datetime import datetime
from typing import List, Dict, Optional


def clean_number(s: str) -> Optional[int]:
    s = s.replace(',', '').strip()
    try:
        return int(s)
    except:
        return None

def now_str() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

GOTO_TIMEOUT = 90_000


class LinkedInScraper:

    def __init__(self, username: str, password: str):
        self.username = username
        self.password = password
        self.pw = None
        self.browser = None
        self.page: Page = None
        self.all_posts: List[Dict] = []
        self.all_people_stats: List[Dict] = []

    # ── Browser ───────────────────────────────────────────────────────────────

    def start(self):
        print("🚀  Starting browser...")
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(headless=False, slow_mo=0)
        ctx = self.browser.new_context(viewport={"width": 1440, "height": 900})
        ctx.set_default_navigation_timeout(GOTO_TIMEOUT)
        ctx.set_default_timeout(15_000)
        self.page = ctx.new_page()
        print("✅  Browser ready\n")

    def stop(self):
        try:
            if self.browser: self.browser.close()
            if self.pw:      self.pw.stop()
        except: pass

    def _goto(self, url: str):
        self.page.goto(url, timeout=GOTO_TIMEOUT, wait_until='domcontentloaded')
        time.sleep(3)

    def _dismiss_popups(self):
        for sel in ['button[aria-label="Dismiss"]', 'button[aria-label="Close"]']:
            try:
                btn = self.page.locator(sel).first
                if btn.is_visible(timeout=1500):
                    btn.click()
                    time.sleep(0.4)
            except: pass

    def _scroll(self, times: int = 5, px: int = 900, pause: float = 1.5):
        for _ in range(times):
            self.page.evaluate(f'window.scrollBy(0, {px})')
            time.sleep(pause)

    # ── Login ─────────────────────────────────────────────────────────────────

    def login(self) -> bool:
        print("🔐  Logging in...")
        self._goto('https://www.linkedin.com/login')
        try:
            for sel in ['input[name="session_key"]',
                        'input[aria-label="Email address or phone number"]',
                        'input#username']:
                try:
                    inp = self.page.locator(sel).first
                    if inp.is_visible(timeout=4000):
                        inp.fill(self.username)
                        break
                except: continue

            for sel in ['input[name="session_password"]', 'input[type="password"]']:
                try:
                    inp = self.page.locator(sel).first
                    if inp.is_visible(timeout=4000):
                        inp.fill(self.password)
                        break
                except: continue

            self.page.locator('button[type="submit"]').first.click()
            self.page.wait_for_url('**/feed/**', timeout=60_000)
            time.sleep(3)
            print("✅  Logged in!\n")
            return True
        except Exception as e:
            try:
                if '/feed' in self.page.url:
                    print("✅  Already on feed!\n")
                    return True
                print("   Please log in manually...")
                self.page.wait_for_url('**/feed/**', timeout=120_000)
                print("✅  Manual login detected!\n")
                return True
            except:
                return False

    # ══════════════════════════════════════════════════════════════════════════
    # POSTS
    # ══════════════════════════════════════════════════════════════════════════

    def scrape_posts(self, slug: str, display: str, max_posts: int = 50) -> List[Dict]:
        print(f"\n   📱  Scraping POSTS for '{display}'...")
        self._goto(f'https://www.linkedin.com/company/{slug}/posts/?feedView=all')
        self._dismiss_popups()

        # Scroll more to load up to max_posts
        scroll_rounds = max(6, max_posts // 3)
        self._scroll(times=scroll_rounds, px=1000, pause=1.5)
        self.page.evaluate('window.scrollTo(0, 0)')
        time.sleep(1)

        # Expand "see more"
        try:
            btns = self.page.locator(
                'button.feed-shared-inline-show-more-text__see-more-less-toggle'
            ).all()
            for btn in btns:
                try: btn.click(timeout=800); time.sleep(0.2)
                except: pass
        except: pass

        # Find containers
        containers = []
        for sel in ['div.feed-shared-update-v2[data-urn]',
                    'div[data-urn*="activity"]',
                    'article.relative',
                    'div.occludable-update']:
            try:
                found = self.page.locator(sel).all()
                if len(found) >= 1:
                    containers = found
                    print(f"   Found {len(found)} containers ({sel})")
                    break
            except: continue

        if not containers:
            print("   ⚠️  No containers — trying JS extraction")
            return self._posts_via_js(slug, display, max_posts)

        posts = []
        for i, c in enumerate(containers[:max_posts]):
            try:
                pdata = {
                    'Company':     display,
                    'Post_Number': i + 1,
                    'Post_Text':   '',
                    'Post_Link':   'N/A',
                    'Likes':       'N/A',
                    'Comments':    'N/A',
                    'Reposts':     'N/A',
                    'Scraped_At':  now_str(),
                }

                for ts in ['div.feed-shared-text-view span[dir="ltr"]',
                           'div.update-components-text span[dir="ltr"]',
                           'span.break-words',
                           'div.feed-shared-text',
                           'div[class*="commentary"]']:
                    try:
                        el = c.locator(ts).first
                        if el.count() and el.is_visible(timeout=800):
                            raw = el.inner_text(timeout=2000)
                            if raw and len(raw.strip()) > 10:
                                pdata['Post_Text'] = raw.strip()
                                break
                    except: continue

                if not pdata['Post_Text']:
                    raw = c.inner_text(timeout=3000)
                    pdata['Post_Text'] = self._clean_post_text(raw)

                try:
                    urn = c.get_attribute('data-urn')
                    if urn:
                        act_id = urn.split(':')[-1]
                        pdata['Post_Link'] = f'https://www.linkedin.com/feed/update/urn:li:activity:{act_id}/'
                    else:
                        link = c.locator('a[href*="/feed/update/"]').first
                        href = link.get_attribute('href')
                        if href:
                            pdata['Post_Link'] = href if href.startswith('http') else f'https://www.linkedin.com{href}'
                except: pass

                try:
                    full = c.inner_text(timeout=2000)
                    m = re.search(r'([\d,]+)\s*reaction', full, re.I)
                    if not m: m = re.search(r'([\d,]+)\s*like', full, re.I)
                    if m: pdata['Likes'] = m.group(1)
                    m = re.search(r'([\d,]+)\s*comment', full, re.I)
                    if m: pdata['Comments'] = m.group(1)
                    m = re.search(r'([\d,]+)\s*repost', full, re.I)
                    if m: pdata['Reposts'] = m.group(1)
                except: pass

                print(f"   Post {i+1}: {pdata['Post_Text'][:80].replace(chr(10),' ')!r}")
                posts.append(pdata)
                time.sleep(0.3)
            except Exception as e:
                print(f"   ⚠️  Post {i+1}: {e}")

        self.all_posts.extend(posts)
        print(f"   ✅  Posts done: {len(posts)}\n")
        return posts

    def _clean_post_text(self, raw: str) -> str:
        stop = {'like','comment','share','repost','send','follow','reaction','view'}
        out = []
        for line in raw.split('\n'):
            line = line.strip()
            if not line: continue
            if any(kw in line.lower() for kw in stop) and len(line) < 45: break
            if re.fullmatch(r'(\d+[smhd]|\d+\s+(second|minute|hour|day|week|month|year)s?\s+ago|just now)', line.lower()):
                continue
            out.append(line)
        return '\n'.join(out)

    def _posts_via_js(self, slug: str, display: str, max_posts: int) -> List[Dict]:
        print("   🔄  JS post extraction...")
        posts = []
        try:
            js_code = r"""
                () => {
                    const posts = [];
                    document.querySelectorAll('[data-urn*="activity"]').forEach((el, i) => {
                        if (i >= 60) return;
                        const textEl = el.querySelector(
                            'div.feed-shared-text-view span[dir="ltr"], ' +
                            'div.update-components-text span[dir="ltr"], ' +
                            'span.break-words'
                        );
                        posts.push({
                            urn: el.getAttribute('data-urn') || '',
                            text: textEl ? textEl.innerText.trim()
                                        : el.innerText.trim().slice(0, 800)
                        });
                    });
                    return posts;
                }
            """
            result = self.page.evaluate(js_code)
            for i, p in enumerate(result[:max_posts]):
                urn = p.get('urn', '')
                act_id = urn.split(':')[-1] if urn else ''
                posts.append({
                    'Company':     display,
                    'Post_Number': i + 1,
                    'Post_Text':   p.get('text', '').strip(),
                    'Post_Link':   f'https://www.linkedin.com/feed/update/urn:li:activity:{act_id}/' if act_id else 'N/A',
                    'Likes':       'N/A', 'Comments': 'N/A', 'Reposts': 'N/A',
                    'Scraped_At':  now_str(),
                })
                print(f"   Post {i+1} (JS): {posts[-1]['Post_Text'][:70]!r}")
        except Exception as e:
            print(f"   ❌  JS posts failed: {e}")
        self.all_posts.extend(posts)
        print(f"   ✅  Posts done (JS): {len(posts)}\n")
        return posts

    # ══════════════════════════════════════════════════════════════════════════
    # PEOPLE STATS — CAROUSEL AWARE
    # ══════════════════════════════════════════════════════════════════════════

    def scrape_people_stats(self, slug: str, display: str) -> List[Dict]:
        print(f"\n   👥  Scraping PEOPLE STATS for '{display}'...")
        self._goto(f'https://www.linkedin.com/company/{slug}/people/')
        self._dismiss_popups()

        # Get total member count
        total_members = 'N/A'
        try:
            body_text = self.page.locator('body').inner_text(timeout=5000)
            m = re.search(r'([\d,]+)\s+associated members', body_text)
            if m:
                total_members = m.group(1)
        except: pass
        print(f"   📊  Total members: {total_members}")

        # Scroll to load carousel into view
        self._scroll(times=4, px=600, pause=1.2)
        self.page.evaluate('window.scrollTo(0, 0)')
        time.sleep(2)

        # Try to scroll carousel into view
        try:
            carousel = self.page.locator(
                'div[class*="carousel"], div[class*="org-people"]'
            ).first
            carousel.scroll_into_view_if_needed()
            time.sleep(1)
        except: pass

        # ── CAROUSEL: collect cards from ALL slides ───────────────────────────
        all_card_data = {}  # heading → list of entries (deduplicated)

        # Collect slide 1
        self._collect_visible_cards(all_card_data)

        # Advance through remaining slides
        for slide_num in range(1, 6):
            clicked = False

            # Try the › arrow button
            for sel in [
                'button[aria-label="Next"]',
                'button.artdeco-carousel__next-button',
                '[class*="carousel__next"]',
                '[class*="carousel"] button:last-child',
                'button[class*="carousel"][class*="next"]',
            ]:
                try:
                    btn = self.page.locator(sel).first
                    if btn.is_visible(timeout=2000) and btn.is_enabled(timeout=1000):
                        btn.click()
                        time.sleep(2.5)
                        self._collect_visible_cards(all_card_data)
                        clicked = True
                        print(f"   ✅  Carousel → slide {slide_num + 1}")
                        break
                except: continue

            # Fallback: try dot indicators
            if not clicked:
                try:
                    dots = self.page.locator(
                        'ol.artdeco-carousel__indicator-list button, '
                        'div[class*="carousel"] button[class*="dot"], '
                        'button[class*="indicator"]'
                    ).all()
                    if slide_num < len(dots):
                        dots[slide_num].click()
                        time.sleep(2.5)
                        self._collect_visible_cards(all_card_data)
                        clicked = True
                        print(f"   Carousel dot {slide_num + 1} clicked")
                except: pass

            if not clicked:
                print(f"   ⚠️  Carousel stopped at slide {slide_num}")
                break

        # ── Build output rows ─────────────────────────────────────────────────
        rows_out = []
        if all_card_data:
            print(f"\n   Cards collected: {list(all_card_data.keys())}")
            for heading, entries in all_card_data.items():
                for rank, entry in enumerate(entries, start=1):
                    rows_out.append({
                        'Company':       display,
                        'Total_Members': total_members,
                        'Category':      heading,
                        'Rank':          rank,
                        'Count':         entry['count'],
                        'Label':         entry['label'],
                        'Scraped_At':    now_str(),
                    })
                print(f"   ✅  '{heading}': {len(entries)} entries")
        else:
            print("   ⚠️  JS carousel method found nothing — trying full body parse")
            try:
                raw = self.page.locator('body').inner_text(timeout=5000)
            except:
                raw = ''
            rows_out = self._parse_people_text(raw, display, total_members)

        if not rows_out:
            print("   ❌  No rows. Page snippet for debug:")
            try:
                print(self.page.locator('body').inner_text(timeout=3000)[:1500])
            except: pass

        self.all_people_stats.extend(rows_out)
        print(f"   ✅  People stats total: {len(rows_out)} rows\n")
        return rows_out

    def _collect_visible_cards(self, all_card_data: dict):
        """
        Read whatever cards are currently visible in the carousel.
        Merges into all_card_data dict (heading → entries list).
        FIXED: removed children.length === 0 constraint that blocked heading detection.
        """
        js_code = r"""
            () => {
                const HEADINGS = [
                    'Where they live',
                    'Where they studied',
                    'What they studied',
                    'What they are skilled at',
                    'What they do',
                    'How they got there',
                ];

                // FIXED: find heading by innerText on any element,
                // no longer requiring children.length === 0
                function findHeadingEl(heading) {
                    const candidates = document.querySelectorAll(
                        'h2, h3, h4, dt, span, p, div, strong, li'
                    );
                    for (const el of candidates) {
                        if (el.innerText && el.innerText.trim() === heading) {
                            return el;
                        }
                    }
                    return null;
                }

                // Walk up to find a container with enough content lines
                function findContainer(el) {
                    let node = el;
                    for (let i = 0; i < 12; i++) {
                        if (!node.parentElement) break;
                        node = node.parentElement;
                        const lines = (node.innerText || '')
                            .split('\n')
                            .filter(l => l.trim()).length;
                        if (lines >= 6) return node;
                    }
                    return el.parentElement || el;
                }

                const cards = [];

                for (const heading of HEADINGS) {
                    const headingEl = findHeadingEl(heading);
                    if (!headingEl) continue;

                    const container = findContainer(headingEl);
                    const cardText = container.innerText || '';
                    const lines = cardText.split('\n')
                        .map(l => l.trim())
                        .filter(Boolean);

                    const entries = [];
                    let i = 0;
                    while (i < lines.length) {
                        const line = lines[i];

                        // Pattern 1: "4,094  |  University of California, Berkeley"
                        const inlineM = line.match(/^([\d,]+)\s*\|\s*(.+)$/);
                        if (inlineM) {
                            const count = parseInt(inlineM[1].replace(/,/g, ''));
                            const label = inlineM[2].trim();
                            if (label !== heading && label !== 'Add'
                                && !label.startsWith('+')) {
                                entries.push({ count, label });
                            }
                            i++; continue;
                        }

                        // Pattern 2: number alone, label on next line
                        const numM = line.match(/^([\d,]+)$/);
                        if (numM && i + 1 < lines.length) {
                            const nxt = lines[i + 1];
                            if (!/^[\d,]+$/.test(nxt) &&
                                nxt !== heading &&
                                nxt !== 'Add' &&
                                !nxt.startsWith('+')) {
                                entries.push({
                                    count: parseInt(numM[1].replace(/,/g, '')),
                                    label: nxt
                                });
                                i += 2; continue;
                            }
                        }
                        i++;
                    }

                    if (entries.length > 0) {
                        cards.push({ heading, entries });
                    }
                }
                return cards;
            }
        """
        try:
            result = self.page.evaluate(js_code)
            for card in (result or []):
                h = card['heading']
                if h not in all_card_data:
                    all_card_data[h] = card['entries']
                else:
                    existing_labels = {e['label'] for e in all_card_data[h]}
                    for entry in card['entries']:
                        if entry['label'] not in existing_labels:
                            all_card_data[h].append(entry)
                            existing_labels.add(entry['label'])
        except Exception as e:
            print(f"   ⚠️  _collect_visible_cards error: {e}")

    def _parse_people_text(self, text: str, company: str, total: str) -> List[Dict]:
        rows = []
        sections = {
            'Where they live':          r'Where they live(.*?)(?=Where they studied|What they studied|What they are skilled at|What they do|How they got|$)',
            'Where they studied':       r'Where they studied(.*?)(?=What they studied|What they are skilled at|What they do|How they got|Where they live|$)',
            'What they studied':        r'What they studied(.*?)(?=What they are skilled at|What they do|How they got|Where they|$)',
            'What they are skilled at': r'What they are skilled at(.*?)(?=What they do|How they got|Where they|What they studied|$)',
            'What they do':             r'What they do(.*?)(?=How they got|Where they|What they studied|What they are|$)',
            'How they got there':       r'How they got there(.*?)(?=Where they|What they|$)',
        }
        for heading, pattern in sections.items():
            m = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
            if not m: continue
            lines = [l.strip() for l in m.group(1).split('\n') if l.strip()]
            entries = []
            i = 0
            while i < len(lines):
                line = lines[i]
                if line in ('Add', '+ Add', heading): i += 1; continue
                inline = re.match(r'^([\d,]+)\s*\|\s*(.+)$', line)
                if inline:
                    count = clean_number(inline.group(1))
                    label = inline.group(2).strip()
                    if count and label and label != heading:
                        entries.append({'count': count, 'label': label})
                    i += 1; continue
                num_only = re.match(r'^([\d,]+)$', line)
                if num_only and i + 1 < len(lines):
                    nxt = lines[i + 1]
                    if not re.match(r'^[\d,]+$', nxt) and nxt not in ('Add', '+ Add', heading):
                        count = clean_number(num_only.group(1))
                        if count:
                            entries.append({'count': count, 'label': nxt})
                        i += 2; continue
                i += 1
            for rank, entry in enumerate(entries, start=1):
                rows.append({
                    'Company': company, 'Total_Members': total,
                    'Category': heading, 'Rank': rank,
                    'Count': entry['count'], 'Label': entry['label'],
                    'Scraped_At': now_str(),
                })
            print(f"   (text-fallback) '{heading}': {len(entries)} entries")
        return rows

    # ══════════════════════════════════════════════════════════════════════════
    # SAVE + RUN
    # ══════════════════════════════════════════════════════════════════════════

    def scrape_company(self, slug: str, display: str, num_posts: int = 50):
        print(f"\n{'='*68}")
        print(f"🏢  {display.upper()}  (slug: {slug})")
        print(f"{'='*68}")
        self.scrape_posts(slug, display, max_posts=num_posts)
        self.scrape_people_stats(slug, display)
        time.sleep(3)

    def save(self):
        print(f"\n{'='*68}\n💾  SAVING\n{'='*68}\n")
        if self.all_posts:
            fname = 'linkedin_posts_v5.csv'
            # utf-8-sig = UTF-8 with BOM → Excel opens correctly, no garbled chars
            with open(fname, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=self.all_posts[0].keys())
                writer.writeheader()
                writer.writerows(self.all_posts)
            print(f"✅  {fname}  ({len(self.all_posts)} rows)")

        if self.all_people_stats:
            fname = 'linkedin_people_stats_v5.csv'
            # utf-8-sig = UTF-8 with BOM → Excel opens correctly, no garbled chars
            with open(fname, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.DictWriter(f, fieldnames=self.all_people_stats[0].keys())
                writer.writeheader()
                writer.writerows(self.all_people_stats)
            print(f"✅  {fname}  ({len(self.all_people_stats)} rows)")
            print("\n   SAMPLE ROWS:")
            for row in self.all_people_stats[:15]:
                print(f"     {row['Company']:15} | {row['Category']:28} | {str(row['Count']):8} | {row['Label']}")

    def run(self, companies: List[Dict], num_posts: int = 50):
        self.start()
        try:
            if not self.login():
                print("❌  Login failed"); return
            for co in companies:
                self.scrape_company(co['slug'], co['display'], num_posts)
            self.save()
        except Exception as e:
            import traceback
            print(f"❌  Fatal: {e}")
            traceback.print_exc()
        finally:
            self.stop()


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':

    USERNAME = 'testacc20262020@gmail.com'
    PASSWORD = 'testaccount2026'

    COMPANIES = [
        {'slug': 'google',                                    'display': 'Google'},
        {'slug': 'traverse-so',                               'display': 'Traverse'},
        {'slug': 'luel',                                      'display': 'Luel'},
        {'slug': 'galactic-resource-utilization-space-inc',   'display': 'Galactic Resource Utilization Space'},
        {'slug': 'overdrive-health',                          'display': 'Overdrive Health'},
        {'slug': 'pirislabs',                                 'display': 'Piris Labs'},
        {'slug': 'axion-orbital',                             'display': 'Axion Orbital'},
        {'slug': '011transportes',                            'display': '011 Transportes'},
        {'slug': 'voxel-energy',                              'display': 'Voxel Energy'},
        {'slug': 'beyond-reach-labs-inc',                     'display': 'Beyond Reach Labs'},
    ]

    scraper = LinkedInScraper(USERNAME, PASSWORD)
    scraper.run(COMPANIES, num_posts=50)
