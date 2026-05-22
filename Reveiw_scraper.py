"""
Google Maps Reviews Scraper (Selenium) — Resumable + Fast-Fail + Commented
UPDATED:
- Avoids fragile #searchboxinput by using Maps search URL
- Block detection fixed (no false positives from normal "traffic" UI)
- Clicks first search result if the place page doesn't auto-open
NEW:
- Reports "reviews collected this run" (not just total CSV count)
- Adds OLDEST_YEAR filter (e.g., 2022–Present)
- Converts relative dates to YYYY-MM-DD (date only, no time)
- Adds reviewer_total_reviews + is_local_guide (best-effort extraction from card text)
"""

import csv
import json
import time
import traceback
from datetime import datetime, date, timedelta
from pathlib import Path
from urllib.parse import quote_plus
import re
import calendar

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
)

from webdriver_manager.chrome import ChromeDriverManager


# ===========================
# CONFIG (edit these)
# ===========================
BUSINESS_NAME = "The Majestic Theatre, Dallas, TX"

# If you have the exact /maps/place/... URL, put it here (most stable).
PLACE_URL = None

HEADLESS = False
TARGET_REVIEWS = 3000
NO_GROWTH_LIMIT = 35
MAX_RUNTIME_SECONDS = 15 * 60

KEEP_BROWSER_OPEN = False

# If Google ever does show consent/captcha, pause so you can fix it manually.
ALLOW_MANUAL_SOLVE_IF_BLOCKED = True

# ---- Date cutoff (e.g., 2022–Present) ----
OLDEST_YEAR = 2022
CUTOFF_DATE = date(OLDEST_YEAR, 1, 1)

# Once we are clearly past the cutoff and getting no new in-range reviews for this many loops, stop.
OLD_CUTOFF_NO_NEW_LOOPS_LIMIT = 12


# ===========================
# OUTPUT PATHS
# ===========================
SAFE_DIR = "".join(c for c in BUSINESS_NAME if c.isalnum() or c in (" ", "_", "-")).strip().replace(" ", "_")
OUTPUT_DIR = Path.home() / "Downloads" / f"google_maps_reviews_{SAFE_DIR}_BCA"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SAFE_FILE = "".join(c for c in BUSINESS_NAME.lower().replace(" ", "_") if c.isalnum() or c in "_-")
CSV_PATH = OUTPUT_DIR / f"{SAFE_FILE}_reviews.csv"
STATE_PATH = OUTPUT_DIR / f"{SAFE_FILE}_state.json"

CSV_FIELDS = [
    "review_id",
    "reviewer_name",
    "reviewer_total_reviews",  # NEW
    "is_local_guide",          # NEW
    "rating",
    "review_date",
    "review_text",
]


# ===========================
# DEBUG HELPERS
# ===========================
def _ts():
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def dump_debug(driver, label: str):
    png = OUTPUT_DIR / f"{label}_{_ts()}.png"
    html = OUTPUT_DIR / f"{label}_{_ts()}.html"
    try:
        driver.save_screenshot(str(png))
    except Exception:
        pass
    try:
        html.write_text(driver.page_source, encoding="utf-8")
    except Exception:
        pass
    print(f"[DEBUG] {label} url={driver.current_url}")
    print(f"[DEBUG] screenshot={png}")
    print(f"[DEBUG] html={html}")


def looks_like_blocked_or_interstitial(driver) -> bool:
    """
    IMPORTANT: Do NOT match generic 'traffic' text (Maps UI contains it).
    Only match real interstitial indicators.
    """
    url = (driver.current_url or "").lower()
    html = (driver.page_source or "").lower()

    # URL-based: strongest signal
    if "consent.google.com" in url:
        return True
    if "google.com/sorry" in url or "/sorry/" in url:
        return True

    # HTML-based: use SPECIFIC phrases (not generic words)
    signals = [
        "our systems have detected unusual traffic",
        "detected unusual traffic",
        "before you continue to google",
        "to continue, please",
        "recaptcha",
        "i'm not a robot",
        "verify you are a human",
    ]
    return any(s in html for s in signals)


def assert_not_blocked(driver, label: str):
    if looks_like_blocked_or_interstitial(driver):
        dump_debug(driver, f"blocked_{label}")

        if ALLOW_MANUAL_SOLVE_IF_BLOCKED:
            print("\n[BLOCKED] Consent/CAPTCHA/unusual-traffic detected.")
            print("Fix it in the opened Chrome window, then press ENTER here.")
            input("Press ENTER to continue...")
            time.sleep(1.0)

            if looks_like_blocked_or_interstitial(driver):
                dump_debug(driver, f"still_blocked_{label}")
                raise RuntimeError("Still blocked after manual attempt. Cannot proceed.")
            return

        raise RuntimeError(
            f"Blocked/interstitial detected at '{label}'. "
            f"See blocked_{label}_*.png/html in {OUTPUT_DIR}"
        )


def try_accept_consent_variants(driver) -> bool:
    """
    Best-effort consent clicker. Consent layouts change.
    If it's a real CAPTCHA, this won't help.
    """
    xpaths = [
        "//button//*[normalize-space()='Accept all']/ancestor::button",
        "//button//*[normalize-space()='I agree']/ancestor::button",
        "//button//*[normalize-space()='Agree']/ancestor::button",
        "//button//*[normalize-space()='Accept']/ancestor::button",
    ]
    for xp in xpaths:
        try:
            btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((By.XPATH, xp)))
            btn.click()
            time.sleep(0.8)
            return True
        except Exception:
            continue
    return False


# ===========================
# DATE PARSING / NORMALIZATION
# ===========================
_MONTHS = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def _add_months(d: date, months: int) -> date:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    last_day = calendar.monthrange(y, m)[1]
    return date(y, m, min(d.day, last_day))


def _add_years(d: date, years: int) -> date:
    y = d.year + years
    last_day = calendar.monthrange(y, d.month)[1]
    return date(y, d.month, min(d.day, last_day))


def normalize_google_date_to_iso(s: str, today: date | None = None) -> str:
    """
    Converts common Google Maps review date strings to YYYY-MM-DD (date only).

    Relative:
      - 'a year ago', '2 years ago'
      - 'a month ago', '3 months ago'
      - '2 weeks ago', '5 days ago'
      - 'yesterday', 'today'

    Absolute (best-effort):
      - 'Jan 2024' / 'January 2024' -> YYYY-MM-01
      - 'Jan 5, 2024' -> YYYY-MM-DD
      - '5 Jan 2024' -> YYYY-MM-DD
      - '1/5/2024' or '01/05/2024' (assumes US month/day/year)

    If it can't parse, returns original string unchanged.
    """
    if not s:
        return ""

    if today is None:
        today = date.today()

    raw = s.strip()
    t = raw.lower().strip()

    if t == "today":
        return today.isoformat()
    if t == "yesterday":
        return (today - timedelta(days=1)).isoformat()

    m = re.match(r"^(a|an|\d+)\s+(day|week|month|year)s?\s+ago$", t)
    if m:
        n_str, unit = m.group(1), m.group(2)
        n = 1 if n_str in ("a", "an") else int(n_str)
        if unit == "day":
            d = today - timedelta(days=n)
        elif unit == "week":
            d = today - timedelta(weeks=n)
        elif unit == "month":
            d = _add_months(today, -n)
        else:
            d = _add_years(today, -n)
        return d.isoformat()

    m = re.match(r"^([a-z]+)\s+(\d{1,2}),\s*(\d{4})$", t)
    if m and m.group(1)[:3] in _MONTHS:
        mon = _MONTHS[m.group(1)[:3]]
        day_ = int(m.group(2))
        yr = int(m.group(3))
        try:
            return date(yr, mon, day_).isoformat()
        except ValueError:
            return raw

    m = re.match(r"^(\d{1,2})\s+([a-z]+)\s+(\d{4})$", t)
    if m and m.group(2)[:3] in _MONTHS:
        day_ = int(m.group(1))
        mon = _MONTHS[m.group(2)[:3]]
        yr = int(m.group(3))
        try:
            return date(yr, mon, day_).isoformat()
        except ValueError:
            return raw

    m = re.match(r"^([a-z]+)\s+(\d{4})$", t)
    if m and m.group(1)[:3] in _MONTHS:
        mon = _MONTHS[m.group(1)[:3]]
        yr = int(m.group(2))
        try:
            return date(yr, mon, 1).isoformat()
        except ValueError:
            return raw

    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", t)
    if m:
        mm = int(m.group(1))
        dd = int(m.group(2))
        yy = int(m.group(3))
        try:
            return date(yy, mm, dd).isoformat()
        except ValueError:
            return raw

    return raw


def iso_to_date_or_none(iso_str: str) -> date | None:
    try:
        return date.fromisoformat(iso_str)
    except Exception:
        return None


# ===========================
# ROBUST FAST DOM SCRAPE (JS)
# ===========================
def extract_all_visible_data(driver):
    return driver.execute_script("""
        function pickLongestText(card) {
            const selectors = ['.wiI7pd','.MyEned .wiI7pd','.MyEned span','[data-expandable-section]'];
            let best = '';
            for (const sel of selectors) {
                const el = card.querySelector(sel);
                const t = (el && el.innerText) ? el.innerText.trim() : '';
                if (t.length > best.length) best = t;
            }
            if (!best) {
                const candidates = card.querySelectorAll('span, div');
                for (const el of candidates) {
                    const t = (el && el.innerText) ? el.innerText.trim() : '';
                    if (t.length > best.length && t.length < 5000) best = t;
                }
            }
            return best;
        }

        function extractContributorMeta(card) {
            // Best-effort: scan text near author + nearby UI for patterns like:
            // "Local Guide · 123 reviews" or "123 reviews"
            let blob = '';

            const authorNode = card.querySelector('.d4r55');
            if (authorNode) {
                const parent = authorNode.closest('div') || authorNode.parentElement;
                if (parent) blob += ' ' + (parent.innerText || '');
            }

            const likely = card.querySelectorAll('button, span, div');
            const limit = Math.min(likely.length, 80);
            for (let i = 0; i < limit; i++) {
                const t = (likely[i].innerText || '').trim();
                if (!t) continue;
                if (/local guide/i.test(t) || /\\breviews?\\b/i.test(t)) {
                    blob += ' ' + t;
                }
            }

            const isLocalGuide = /local guide/i.test(blob);

            let reviewerTotalReviews = '';
            const m = blob.match(/(\\d[\\d,]*)\\s+reviews?/i);
            if (m && m[1]) reviewerTotalReviews = m[1].replace(/,/g, '');

            return { isLocalGuide, reviewerTotalReviews };
        }

        let reviews = [];
        let cards = document.querySelectorAll('[data-review-id]');
        cards.forEach(card => {
            const id = card.getAttribute('data-review-id') || '';
            const author = card.querySelector('.d4r55')?.innerText?.trim() || '';
            const rating = card.querySelector('.kvMY7b, .kvMYJc')?.getAttribute('aria-label') || '';
            const date = card.querySelector('.rsqaWe')?.innerText?.trim() || '';
            const text = pickLongestText(card);

            const meta = extractContributorMeta(card);

            reviews.push({
                id,
                author,
                text,
                rating,
                date,
                is_local_guide: meta.isLocalGuide,
                reviewer_total_reviews: meta.reviewerTotalReviews
            });
        });
        return reviews;
    """)


# ===========================
# DRIVER
# ===========================
def init_driver():
    options = Options()
    options.set_capability("pageLoadStrategy", "eager")

    options.add_argument("--window-size=1920,1080")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--lang=en-US")
    options.add_argument("--accept-lang=en-US,en")
    options.add_argument("--no-first-run")
    options.add_argument("--no-default-browser-check")

    # reduce load
    options.add_argument("--blink-settings=imagesEnabled=false")
    prefs = {
        "profile.managed_default_content_settings.images": 2,
        "profile.default_content_setting_values.images": 2,
    }
    options.add_experimental_option("prefs", prefs)

    if HEADLESS:
        options.add_argument("--headless=new")

    if KEEP_BROWSER_OPEN:
        options.add_experimental_option("detach", True)

    log_path = str(OUTPUT_DIR / "chromedriver.log")
    service = Service(ChromeDriverManager().install(), log_output=log_path)

    driver = webdriver.Chrome(service=service, options=options)
    return driver


# ===========================
# CARD FINDING (fallbacks)
# ===========================
def find_review_cards(driver):
    cards = driver.find_elements(By.CSS_SELECTOR, "[data-review-id]")
    if cards:
        return cards

    cards = driver.find_elements(By.CSS_SELECTOR, "div.jftiEf")
    if cards:
        return cards

    cards = driver.find_elements(By.XPATH, "//*[@data-review-id]")
    if cards:
        return cards

    return driver.find_elements(By.XPATH, "//div[contains(@class,'jftiEf')]")


def wait_for_cards(driver, timeout_s=25):
    WebDriverWait(driver, timeout_s).until(lambda d: len(find_review_cards(d)) >= 3)
    return True


# ===========================
# NAVIGATION (NO searchboxinput)
# ===========================
def open_place_page(driver, business_name: str):
    wait = WebDriverWait(driver, 35)

    print("[STEP] Open Google Maps")
    driver.get("https://www.google.com/maps?hl=en")
    time.sleep(1.2)

    try_accept_consent_variants(driver)
    assert_not_blocked(driver, "maps_home")

    if PLACE_URL:
        print("[STEP] Open PLACE_URL directly")
        driver.get(PLACE_URL)
        time.sleep(1.2)
        assert_not_blocked(driver, "place_url")
    else:
        print("[STEP] Open search URL (bypass fragile searchbox)")
        q = quote_plus(business_name)
        driver.get(f"https://www.google.com/maps/search/?api=1&query={q}&hl=en")
        time.sleep(1.6)
        assert_not_blocked(driver, "search_url")

        try:
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1")))
        except TimeoutException:
            print("[WARN] Place header not found. Clicking first place result...")
            first = wait.until(
                EC.element_to_be_clickable((By.XPATH, "(//a[contains(@href, '/maps/place')])[1]"))
            )
            driver.execute_script("arguments[0].click();", first)
            time.sleep(1.2)
            assert_not_blocked(driver, "after_first_result_click")
            wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "h1")))

    print("[INFO] Place page loaded:", driver.current_url)


def open_reviews_panel(driver):
    wait = WebDriverWait(driver, 30)

    try:
        print("[STEP] Click Reviews button")
        reviews_btn = wait.until(
            EC.element_to_be_clickable(
                (By.CSS_SELECTOR, "button[aria-label*='Reviews'], button[data-item-id*='reviews']")
            )
        )
        driver.execute_script("arguments[0].click();", reviews_btn)
    except TimeoutException:
        print("[WARN] Reviews button not found. Trying XPath fallback.")
        reviews_btn = wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//button[contains(@aria-label,'Reviews') or contains(@data-item-id,'reviews')]")
            )
        )
        driver.execute_script("arguments[0].click();", reviews_btn)

    wait_for_cards(driver, timeout_s=30)
    print("[INFO] Reviews panel opened")


# ===========================
# FAST-FAIL VALIDATION
# ===========================
def fast_fail_validate_text(driver, min_samples=20, min_nonempty=3):
    time.sleep(0.8)
    rows = extract_all_visible_data(driver) or []
    sample = rows[:min_samples]
    nonempty = sum(1 for r in sample if (r.get("text") or "").strip())
    print(f"[FASTFAIL] sample={len(sample)} nonempty_text={nonempty}")

    if len(sample) >= min_samples and nonempty < min_nonempty:
        dump_debug(driver, "fastfail_no_text")
        raise RuntimeError("FAST FAIL: review text extraction is mostly empty.")


# ===========================
# SCROLL CONTAINER
# ===========================
def get_scroll_container(driver, timeout_s=25):
    end = time.time() + timeout_s
    last_err = None

    while time.time() < end:
        try:
            cards = find_review_cards(driver)
            if not cards:
                try:
                    WebDriverWait(driver, 2).until(lambda d: len(find_review_cards(d)) >= 1)
                except TimeoutException:
                    pass
                continue

            candidates = driver.find_elements(
                By.XPATH,
                "//div[contains(@class,'m6QErb') and contains(@class,'DxyBCb') and contains(@class,'kA9KIf')]"
            )
            for c in candidates:
                try:
                    has_cards = driver.execute_script(
                        "return arguments[0].querySelectorAll('[data-review-id], div.jftiEf').length;",
                        c
                    )
                    is_scrollable = driver.execute_script(
                        "return arguments[0].scrollHeight > arguments[0].clientHeight + 10;",
                        c
                    )
                    if is_scrollable and has_cards and has_cards > 0:
                        return c
                except Exception:
                    continue

            card = cards[0]
            container = driver.execute_script(
                """
                let el = arguments[0];
                for (let i = 0; i < 35 && el; i++) {
                    if (el.scrollHeight && el.clientHeight && el.scrollHeight > el.clientHeight + 10) return el;
                    el = el.parentElement;
                }
                return null;
                """,
                card
            )
            if container:
                return container

        except Exception as e:
            last_err = e

        try:
            WebDriverWait(driver, 2).until(lambda d: len(find_review_cards(d)) >= 1)
        except TimeoutException:
            pass

    raise RuntimeError(f"Could not locate scrollable reviews container. Last error: {last_err}")


def _marker(driver, container):
    cards = find_review_cards(driver)
    count = len(cards)
    last_id = ""
    try:
        if cards:
            last_id = cards[-1].get_attribute("data-review-id") or ""
    except Exception:
        last_id = ""
    try:
        sh = driver.execute_script("return arguments[0].scrollHeight || 0;", container) or 0
    except Exception:
        sh = 0
    return (count, last_id, sh)


def wait_for_new_content(driver, container, prev_marker, timeout_s=5):
    WebDriverWait(driver, timeout_s).until(lambda d: _marker(d, container) != prev_marker)
    return True


def scroll_container_to_bottom(driver, container):
    try:
        driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight;", container)
        return True
    except Exception:
        return False


# ===========================
# HELPERS: TRUNCATION + SAFE CLICK
# ===========================
def looks_truncated(text: str) -> bool:
    t = (text or "").strip()
    return t.endswith("...") or t.endswith("…")


def url_looks_like_profile(url: str) -> bool:
    u = (url or "").lower()
    return ("/contrib/" in u) or ("maps/contrib" in u) or ("contrib" in u)


def safe_click(driver, el) -> bool:
    before = driver.current_url
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", el)
        time.sleep(0.01)
        try:
            ActionChains(driver).move_to_element(el).pause(0.01).click(el).perform()
        except Exception:
            try:
                el.click()
            except (ElementClickInterceptedException, StaleElementReferenceException):
                driver.execute_script("arguments[0].click();", el)
    except Exception:
        return False

    time.sleep(0.05)

    after = driver.current_url
    if after != before and url_looks_like_profile(after):
        try:
            driver.back()
            time.sleep(0.2)
        except Exception:
            pass
        return False

    return True


def extract_full_text_from_card(driver, card) -> str:
    texts = []
    for xp in [
        ".//*[contains(@class,'wiI7pd')]",
        ".//*[@data-expandable-section]",
        ".//*[contains(@class,'MyEned')]//*[self::span or self::div]",
    ]:
        try:
            nodes = card.find_elements(By.XPATH, xp)
            for n in nodes:
                t = (driver.execute_script("return arguments[0].innerText;", n) or "").strip()
                if t:
                    texts.append(t)
        except Exception:
            pass

    if not texts:
        return ""
    return max(texts, key=len)


def expand_card_until_full(driver, card, max_tries=4) -> int:
    clicks = 0
    for _ in range(max_tries):
        before = extract_full_text_from_card(driver, card)
        if not looks_truncated(before):
            break

        selectors = [
            ".//button[contains(@jsaction,'pane.review.expandReview')]",
            ".//button[contains(@class,'w8nwRe')]",
            ".//button[.//span[normalize-space()='More'] or normalize-space()='More']",
            ".//*[@role='button' and (contains(.,'More') or contains(.,'…More') or contains(.,'...More'))]",
        ]

        clicked_this_round = False
        for sel in selectors:
            try:
                btns = card.find_elements(By.XPATH, sel)
                for b in btns:
                    if not b.is_displayed():
                        continue
                    if safe_click(driver, b):
                        clicks += 1
                        clicked_this_round = True

                        try:
                            WebDriverWait(driver, 2).until(
                                lambda d: (len(extract_full_text_from_card(d, card)) > len(before) + 5)
                                or (not looks_truncated(extract_full_text_from_card(d, card)))
                            )
                        except TimeoutException:
                            pass

                        after = extract_full_text_from_card(driver, card)
                        if (len(after) > len(before) + 5) or (not looks_truncated(after)):
                            return clicks
            except StaleElementReferenceException:
                return clicks
            except Exception:
                continue

        if not clicked_this_round:
            break

    return clicks


def fix_mojibake(text: str) -> str:
    if not text:
        return text
    return (text.replace("‚Ä¶", "…").replace("â€¦", "…").replace("Â", ""))


def make_review_key_from_js(r: dict):
    rid = (r.get("id") or "").strip()
    if rid:
        return ("id", rid)

    return (
        "fallback",
        (r.get("author") or "").strip(),
        (r.get("rating") or "").strip(),
        (r.get("date") or "").strip(),
        (r.get("text") or "")[:80],
    )


def load_seen_from_csv(csv_path: Path):
    seen = set()
    existing_rows = 0
    if not csv_path.exists():
        return seen, existing_rows

    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            existing_rows += 1
            rid = (row.get("review_id") or "").strip()
            if rid:
                seen.add(("id", rid))
            else:
                seen.add((
                    "fallback",
                    (row.get("reviewer_name") or "").strip(),
                    (row.get("rating") or "").strip(),
                    (row.get("review_date") or "").strip(),
                    (row.get("review_text") or "")[:80],
                ))
    return seen, existing_rows


def ensure_csv_header_compatible(csv_path: Path):
    """
    If the CSV exists but schema is older/different, STOP.
    Otherwise you'll append mismatched columns and corrupt the dataset.
    """
    if not csv_path.exists():
        return

    with csv_path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader, None) or []

    missing = [c for c in CSV_FIELDS if c not in header]
    if missing:
        raise RuntimeError(
            f"Existing CSV header is missing columns {missing}. "
            f"Rename/delete the existing CSV or migrate it, then rerun.\nCSV: {csv_path}"
        )


def append_rows(csv_path: Path, rows: list[dict]):
    file_exists = csv_path.exists()
    with csv_path.open("a", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if not file_exists:
            w.writeheader()
        for r in rows:
            w.writerow(r)
        f.flush()


def save_state(payload: dict):
    payload = dict(payload)
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(STATE_PATH)


def collect_reviews_incremental(driver):
    print(f"[STEP] Collect up to {TARGET_REVIEWS} reviews (resumable + robust text)")
    print(f"[FILTER] Keeping reviews from {CUTOFF_DATE.isoformat()} to Present")

    seen, already = load_seen_from_csv(CSV_PATH)
    ensure_csv_header_compatible(CSV_PATH)

    print(f"[RESUME] Existing rows in CSV: {already}")

    save_state({
        "business": BUSINESS_NAME,
        "already_in_csv": already,
        "csv_path": str(CSV_PATH),
        "oldest_year": OLDEST_YEAR,
        "cutoff_date": CUTOFF_DATE.isoformat(),
    })

    start = time.time()
    container = get_scroll_container(driver)

    stagnant = 0
    total_saved = already
    added_this_run = 0  # explicit “reviews done this run”
    old_cutoff_no_new_loops = 0

    today = date.today()
    oldest_visible_parsed = None

    while True:
        if time.time() - start > MAX_RUNTIME_SECONDS:
            print("[INFO] Max runtime reached; stopping.")
            break

        if total_saved >= TARGET_REVIEWS:
            print("[INFO] Target reached (based on CSV count).")
            break

        cards = find_review_cards(driver)

        expand_clicks = 0
        trunc_on_screen_before = 0

        for card in cards:
            try:
                current_txt = extract_full_text_from_card(driver, card)
                if looks_truncated(current_txt):
                    trunc_on_screen_before += 1
                    expand_clicks += expand_card_until_full(driver, card, max_tries=4)
            except Exception:
                continue

        js_rows = extract_all_visible_data(driver) or []

        new_rows = []
        added_this_loop = 0
        still_truncated_after = 0
        empty_text_count = 0
        skipped_old_cutoff = 0
        parsed_dates = []

        for r in js_rows:
            try:
                r = r or {}
                author = fix_mojibake((r.get("author") or "").strip())
                rating = (r.get("rating") or "").strip()

                raw_date = fix_mojibake((r.get("date") or "").strip())
                norm_date = normalize_google_date_to_iso(raw_date, today=today)
                d_obj = iso_to_date_or_none(norm_date)
                if d_obj:
                    parsed_dates.append(d_obj)

                text = fix_mojibake((r.get("text") or "").strip())
                review_id = (r.get("id") or "").strip()

                # NEW meta fields (best-effort)
                reviewer_total_reviews = (r.get("reviewer_total_reviews") or "").strip()
                is_local_guide = bool(r.get("is_local_guide"))

                if not text:
                    empty_text_count += 1
                if looks_truncated(text):
                    still_truncated_after += 1

                k = make_review_key_from_js(r)
                if k in seen:
                    continue

                if not author and not text:
                    continue

                # Cutoff filter: only enforce when date parsed
                if d_obj and d_obj < CUTOFF_DATE:
                    skipped_old_cutoff += 1
                    continue

                seen.add(k)
                new_rows.append({
                    "review_id": review_id,
                    "reviewer_name": author,
                    "reviewer_total_reviews": reviewer_total_reviews,
                    "is_local_guide": is_local_guide,
                    "rating": rating,
                    "review_date": norm_date,   # normalized if parseable, else raw string
                    "review_text": text,
                })
                added_this_loop += 1
            except Exception:
                continue

        if parsed_dates:
            oldest_visible_parsed = min(parsed_dates)

        if new_rows:
            append_rows(CSV_PATH, new_rows)
            total_saved += len(new_rows)
            added_this_run += len(new_rows)

            save_state({
                "business": BUSINESS_NAME,
                "total_saved": total_saved,
                "added_this_run": added_this_run,
                "last_added": len(new_rows),
                "stagnant": stagnant,
                "cutoff_date": CUTOFF_DATE.isoformat(),
                "oldest_visible_parsed": oldest_visible_parsed.isoformat() if oldest_visible_parsed else None,
            })

        past_cutoff_now = bool(oldest_visible_parsed and oldest_visible_parsed < CUTOFF_DATE)
        if past_cutoff_now and added_this_loop == 0:
            old_cutoff_no_new_loops += 1
        else:
            old_cutoff_no_new_loops = 0

        print(
            f"[PROGRESS] total_saved={total_saved} | added_this_run={added_this_run} | "
            f"added_this_loop={added_this_loop} | skipped_old_cutoff={skipped_old_cutoff} | "
            f"on_screen={len(cards)} | js_rows={len(js_rows)} | expand_clicks={expand_clicks} | "
            f"truncated_before={trunc_on_screen_before} | truncated_after={still_truncated_after} | "
            f"empty_text_in_js_rows={empty_text_count} | "
            f"oldest_visible_parsed={(oldest_visible_parsed.isoformat() if oldest_visible_parsed else 'N/A')}"
        )

        if old_cutoff_no_new_loops >= OLD_CUTOFF_NO_NEW_LOOPS_LIMIT:
            print(
                f"[INFO] Past cutoff ({CUTOFF_DATE.isoformat()}) and no new in-range reviews "
                f"for {OLD_CUTOFF_NO_NEW_LOOPS_LIMIT} loops; stopping early."
            )
            break

        stagnant = stagnant + 1 if added_this_loop == 0 else 0
        if stagnant >= NO_GROWTH_LIMIT:
            print("[INFO] No new unique reviews; stopping early.")
            break

        prev = _marker(driver, container)
        moved = scroll_container_to_bottom(driver, container)

        if not moved:
            print("[WARN] Scroll did not move; stopping.")
            break

        try:
            wait_for_new_content(driver, container, prev, timeout_s=5)
        except TimeoutException:
            time.sleep(0.05)

    print(f"[DONE] CSV: {CSV_PATH}")
    print(f"[DONE] State JSON: {STATE_PATH}")
    print(f"[DONE] Reviews collected this run: {added_this_run}")
    return CSV_PATH


def main():
    driver = init_driver()
    try:
        open_place_page(driver, BUSINESS_NAME)
        open_reviews_panel(driver)

        fast_fail_validate_text(driver, min_samples=20, min_nonempty=3)

        csv_path = collect_reviews_incremental(driver)
        print(f"[DONE] Output: {csv_path}")

        if KEEP_BROWSER_OPEN:
            input("Press ENTER to exit Python...")

    finally:
        if not KEEP_BROWSER_OPEN:
            driver.quit()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("[ERROR]", e)
        print(traceback.format_exc())
        input("Press ENTER to close...")
