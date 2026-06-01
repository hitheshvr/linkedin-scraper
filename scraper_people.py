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

    def scrape(self, slug, name) -> list:
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

        rows = []
        for category in VALID_CATEGORIES:
            for rank, e in enumerate(all_collected.get(category, []), start=1):
                rows.append({
                    "Company":       name,
                    "Total_Members": total,
                    "Category":      category,
                    "Rank":          rank,
                    "Count":         e["count"],
                    "Label":         e["label"],
                    "Scraped_At":    datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                })

        print(f"  ✅ People rows added: {len(rows)}")
        print(f"  📋 Categories: {list(all_collected.keys())}")
        return rows