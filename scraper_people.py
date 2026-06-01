import re
import time
from datetime import datetime
from utils import VALID_CATEGORIES, JUNK, CLASS_TO_CATEGORY, parse_entries


class PeopleScraper:

    def __init__(self, browser):
        self.browser = browser
        self.page    = browser.page

    def _total_dots(self) -> int:
        try:
            return len(self.page.locator(
                "ol.artdeco-carousel__indicator-list button"
            ).all())
        except:
            return 0

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

    def _next_slide(self) -> bool:
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

    def _extract_entries_from_card(self, card) -> list:
        entries     = []
        seen_labels = set()

        for btn_sel in [
            "button[class*='org-people-bar-graph-element']",
            "li[class*='org-people-bar-graph-element']",
            "div[class*='org-people-bar-graph-element']",
        ]:
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
                                }""", handle
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
                        parts = [p.strip() for p in raw_text.splitlines() if p.strip()]
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
                    break
            except:
                pass

        if not entries:
            try:
                raw = card.inner_text(timeout=3000)
                entries = parse_entries(raw.splitlines())
            except:
                pass

        if not entries:
            try:
                handle = card.element_handle(timeout=1000)
                if handle:
                    raw = self.page.evaluate(
                        "el => el.innerText || el.textContent || ''", handle
                    )
                    entries = parse_entries(raw.splitlines())
            except:
                pass

        if not entries:
            try:
                from bs4 import BeautifulSoup
                handle = card.element_handle(timeout=1000)
                if handle:
                    html = self.page.evaluate("el => el.outerHTML", handle)
                    soup = BeautifulSoup(html, "lxml")
                    entries = parse_entries(soup.get_text(separator="\n").splitlines())
            except:
                pass

        return entries

    def _detect_category(self, card) -> str:
        category = None
        try:
            title_el = card.locator("div.insight-container__title").first
            raw = title_el.inner_text(timeout=2000).strip()
            for line in raw.splitlines():
                if line.strip() in VALID_CATEGORIES:
                    category = line.strip()
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
                    if line.strip() in VALID_CATEGORIES:
                        category = line.strip()
                        break
            except:
                pass

        if not category:
            try:
                from bs4 import BeautifulSoup
                handle = card.element_handle(timeout=1000)
                if handle:
                    html = self.page.evaluate("el => el.outerHTML", handle)
                    soup = BeautifulSoup(html, "lxml")
                    for line in soup.get_text(separator="\n").splitlines():
                        if line.strip() in VALID_CATEGORIES:
                            category = line.strip()
                            break
            except:
                pass

        return category

    def _find_all_cards_on_page(self) -> list:
        card_selectors = [
            "div[class*='org-people-bar-graph-module__geo-region']",
            "div[class*='org-people-bar-graph-module__organization']",
            "div[class*='org-people-bar-graph-module__current-function']",
            "div[class*='org-people-bar-graph-module__degree']",
            "div[class*='org-people-bar-graph-module__field-of-study']",
            "div[class*='org-people-bar-graph-module__skill']",
            "div.insight-container",
            "div[class*='org-people-insights-module']",
        ]
        found_cards = []
        seen_ids    = set()
        for sel in card_selectors:
            try:
                for card in self.page.locator(sel).all():
                    cid = ""
                    try:
                        cid = card.get_attribute("id") or ""
                    except:
                        pass
                    if cid and cid in seen_ids:
                        continue
                    if cid:
                        seen_ids.add(cid)
                    found_cards.append(card)
            except:
                pass
        return found_cards

    # ── FIXED: scrapes ALL members, not just first card ──────────────
    def _scrape_member_cards(self, name) -> list:
        rows       = []
        scraped_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        seen_links = set()
        seen_names = set()

        print(f"  👤 Scraping member cards for {name}...")

        # Scroll down past the carousel to load member cards
        # More scrolls needed to get past the stats carousel
        for _ in range(8):
            self.page.mouse.wheel(0, 600)
            time.sleep(1.2)

        # ── Try ALL known selectors and collect from ALL of them ──
        # LinkedIn uses different class names for the employee grid
        all_member_selectors = [
            # Most common — the profile card wrapper
            "div.org-people-profile-card__card-spacing",
            # Alternate class names LinkedIn uses
            "div[class*='org-people-profile-card__card-spacing']",
            "li[class*='org-people-profiles-module__profile-list-item']",
            # Entity lockup (used in newer LinkedIn layouts)
            "div.artdeco-entity-lockup__content",
            # Generic people card containers
            "div[class*='org-people__emphasis-card']",
            "div[class*='member-card']",
        ]

        member_cards = []
        for sel in all_member_selectors:
            try:
                cards = self.page.locator(sel).all()
                if len(cards) > len(member_cards):
                    member_cards = cards
                    print(f"    Selector '{sel}' found {len(cards)} cards")
            except:
                pass

        # If still nothing, try getting all links with /in/ and
        # building member data directly from anchor tags
        if not member_cards:
            print("    ⚠️  No card containers found — falling back to link scan")
            try:
                anchors = self.page.locator("a[href*='/in/']").all()
                print(f"    Found {len(anchors)} profile links via anchor scan")
                for a in anchors:
                    try:
                        href = a.get_attribute("href") or ""
                        if "/in/" not in href:
                            continue
                        profile_link = href.split("?")[0]
                        if profile_link in seen_links:
                            continue

                        # Skip LinkedIn's own nav/sidebar links
                        if any(x in profile_link for x in [
                            "/in/undefined", "linkedin.com/in/sign",
                        ]):
                            continue

                        seen_links.add(profile_link)

                        # Try to get name and tagline from surrounding elements
                        member_name = "N/A"
                        tagline     = "N/A"
                        try:
                            txt = a.inner_text(timeout=1000).strip()
                            if txt and len(txt) > 1 and txt.lower() not in JUNK:
                                member_name = txt
                        except:
                            pass

                        if member_name != "N/A":
                            rows.append({
                                "Company":      name,
                                "Member_Name":  member_name,
                                "Profile_Link": profile_link,
                                "One_Liner":    tagline,
                                "Scraped_At":   scraped_at,
                            })
                    except:
                        pass
            except:
                pass
            return rows

        print(f"    Total member cards to process: {len(member_cards)}")

        for i, card in enumerate(member_cards):
            try:
                # Scroll into view to trigger lazy loading
                try:
                    card.scroll_into_view_if_needed(timeout=2000)
                    time.sleep(0.4)
                except:
                    pass

                # ── Name: try multiple selectors ──
                member_name = "N/A"
                name_selectors = [
                    "div.artdeco-entity-lockup__title",
                    "span[class*='entity-result__title-text']",
                    "div[class*='lockup__title']",
                    "span.org-people-profile-card__profile-title",
                    "div[class*='profile-card__name']",
                    # Text inside the profile link itself
                    "a[href*='/in/'] span[aria-hidden='true']",
                    "a[href*='/in/']",
                ]
                for sel in name_selectors:
                    try:
                        els = card.locator(sel).all()
                        for el in els:
                            txt = el.inner_text(timeout=800).strip()
                            # Filter out junk and connection degree badges
                            if (txt
                                    and len(txt) > 1
                                    and txt.lower() not in JUNK
                                    and not re.match(r"^\d+(st|nd|rd|th)$", txt)
                                    and txt not in ("·", "--", "Connect", "Follow",
                                                    "Message", "LinkedIn Member")):
                                member_name = txt
                                break
                        if member_name != "N/A":
                            break
                    except:
                        pass

                # ── Profile link ──
                profile_link = "N/A"
                try:
                    for a in card.locator("a").all():
                        href = a.get_attribute("href") or ""
                        if "/in/" in href:
                            profile_link = href.split("?")[0]
                            break
                except:
                    pass

                # Skip duplicates
                if profile_link != "N/A" and profile_link in seen_links:
                    continue
                if member_name != "N/A" and member_name in seen_names:
                    continue
                if profile_link != "N/A":
                    seen_links.add(profile_link)
                if member_name != "N/A":
                    seen_names.add(member_name)

                # ── One-liner / tagline ──
                tagline = "N/A"
                tagline_selectors = [
                    "div.artdeco-entity-lockup__subtitle",
                    "div[class*='lockup__subtitle']",
                    "div.org-people-profile-card__profile-info",
                    "span[class*='entity-result__primary-subtitle']",
                    "div[class*='profile-card__subtitle']",
                    "div[class*='profile-card__occupation']",
                ]
                for sel in tagline_selectors:
                    try:
                        els = card.locator(sel).all()
                        for el in els:
                            txt = el.inner_text(timeout=800).strip()
                            if (txt
                                    and txt.lower() not in JUNK
                                    and txt not in ("--", "·")):
                                tagline = txt
                                break
                        if tagline != "N/A":
                            break
                    except:
                        pass

                # Only save if we got something useful
                if member_name != "N/A" or profile_link != "N/A":
                    rows.append({
                        "Company":      name,
                        "Member_Name":  member_name,
                        "Profile_Link": profile_link,
                        "One_Liner":    tagline,
                        "Scraped_At":   scraped_at,
                    })
                    print(f"    ✅ {i+1}: {member_name} | {tagline[:55]}")

            except Exception as e:
                print(f"    ❌ Card {i+1}: {e}")

        print(f"  ✅ Total members scraped for {name}: {len(rows)}")
        return rows

    def scrape(self, slug, name):
        print(f"\n👥 People: {name}")
        self.browser.goto(f"https://www.linkedin.com/company/{slug}/people/")
        time.sleep(5)

        for _ in range(3):
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

        all_collected = {}
        total_dots = self._total_dots()
        max_slides = max(total_dots, 6) if total_dots > 0 else 6
        print(f"  🎠 Carousel dots: {total_dots}, will cycle {max_slides} slides")

        for slide in range(max_slides):
            print(f"  ➡  Slide {slide + 1}/{max_slides}")
            try:
                self.page.locator(
                    "ol.artdeco-carousel__indicator-list"
                ).first.scroll_into_view_if_needed(timeout=3000)
                time.sleep(1)
            except:
                pass

            for card in self._find_all_cards_on_page():
                try:
                    card.scroll_into_view_if_needed(timeout=3000)
                    time.sleep(0.8)
                except:
                    pass

                category = self._detect_category(card)
                if not category:
                    continue
                entries = self._extract_entries_from_card(card)
                if not entries:
                    continue

                all_collected.setdefault(category, [])
                new = 0
                for e in entries:
                    if not any(x["label"] == e["label"]
                               for x in all_collected[category]):
                        all_collected[category].append(e)
                        new += 1
                        print(f"       [{category}] {str(e['count']):>6} | {e['label']}")
                if new:
                    print(f"    ✅ {category}: +{new} "
                          f"(total {len(all_collected[category])})")

            print(f"    Categories so far: {list(all_collected.keys())}")

            if len(all_collected) >= len(VALID_CATEGORIES):
                if all(len(all_collected.get(c, [])) > 0 for c in VALID_CATEGORIES):
                    print("    ✅ All categories collected — stopping early")
                    break

            active_idx = self._get_active_slide_index()
            n_dots     = self._total_dots()
            if n_dots > 0 and active_idx >= n_dots - 1:
                print(f"    🛑 Last dot — done")
                break
            if not self._next_slide():
                print("    🛑 No more slides")
                break

        # Stats rows
        stats_rows = []
        for category in VALID_CATEGORIES:
            for rank, e in enumerate(all_collected.get(category, []), start=1):
                stats_rows.append({
                    "Company":       name,
                    "Total_Members": total,
                    "Category":      category,
                    "Rank":          rank,
                    "Count":         e["count"],
                    "Label":         e["label"],
                    "Scraped_At":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })

        print(f"  ✅ People stats rows: {len(stats_rows)}")
        print(f"  📋 Categories: {list(all_collected.keys())}")

        # Member card rows — page is already on /people/ URL
        member_rows = self._scrape_member_cards(name)
        print(f"  ✅ Member rows: {len(member_rows)}")

        return stats_rows, member_rows