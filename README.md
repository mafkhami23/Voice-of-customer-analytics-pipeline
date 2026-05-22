# 🎭 Voice of Customer Analytics Pipeline

### Scalable Review Intelligence for Experience Benchmarking

This project builds a data pipeline for extracting and analyzing large-scale Google Maps reviews to surface patterns in visitor experience across venues. Unstructured text is transformed into structured insights on sentiment, topics, and pain points — enabling cross-venue comparison and identifying high-impact areas for improvement.

---

## 📁 Repository Structure

| File | Description |
|---|---|
| `Reveiw_scraper.py` | Google Maps reviews with date filtering, Local Guide flag, and reviewer total review count |

| `Review_Count.py` | Counts keyword mentions per star rating; exports pivot table to Excel |
| `Sentiment_Luke.py` | VADER sentiment analysis (Positive / Neutral / Negative) per review; exports to Excel |
| `Word_Frequency.py` | TF-IDF dominant term extraction (unigrams + bigrams); no manual keyword list required |
| `Word_RAKE.py` | RAKE keyphrase extraction + semantic embedding classification into UX vs. Architecture categories |

---

## ⚙️ Requirements

- Python 3.10+
- Google Chrome (for scrapers)

Install all dependencies:

```bash
pip install selenium webdriver-manager pandas openpyxl nltk scikit-learn rake-nltk sentence-transformers numpy
```

---

## 🚀 Usage

### 1. Scrape Reviews — `Reveiw_scraper.py` (recommended)

Edit the `CONFIG` section at the top of the file:

| Parameter | Description |
|---|---|
| `BUSINESS_NAME` | Name of the place to search (required) |
| `PLACE_URL` | Optional direct `/maps/place/...` URL — most stable |
| `HEADLESS` | Run Chrome headless (`False` by default) |
| `TARGET_REVIEWS` | Stop after this many CSV rows |
| `NO_GROWTH_LIMIT` | Stop after this many scrolls with no new reviews |
| `MAX_RUNTIME_SECONDS` | Hard time cap |
| `OLDEST_YEAR` | Only keep reviews from this year onward (e.g., `2022`) |

```bash
python Reveiw_scraper.py
```

**Output directory:** `~/Downloads/google_maps_reviews_<BUSINESS_NAME>_BCA/`

Output files:
- `<business>_reviews.csv` — scraped reviews
- `<business>_state.json` — resumable state and progress metadata
- `chromedriver.log` — ChromeDriver logs
- `blocked_*.png/html` — debug artifacts if a block/CAPTCHA screen is detected

CSV columns: `review_id`, `reviewer_name`, `reviewer_total_reviews`, `is_local_guide`, `rating`, `review_date`, `review_text`

> `review_date` is normalized to `YYYY-MM-DD` when parseable (handles relative dates like "3 months ago", "a year ago", etc.)

---

### 2. Count Keywords by Rating — `Review_Count.py`

Edit the script:
- `csv_path` — path to your reviews CSV
- `keywords` — list of terms to track (word-boundary matched)
- `base_dir` — output directory

```bash
python Review_Count.py
```

You will be prompted for a building name. Output: `<base_dir>/<building>_KeywordCount.xlsx`

---

### 3. Sentiment Analysis — `Sentiment_Luke.py`

Edit the script:
- `csv_path` — path to your reviews CSV
- `COLUMN_TO_CHECK` — text column to analyze (default: `review_text`)

```bash
python Sentiment_Luke.py
```

You will be prompted for a building name. Output: `<building>_sentiment_results.xlsx`

VADER thresholds: Negative ≤ −0.05, Positive ≥ 0.05, Neutral in between.

---

### 4. Dominant Term Extraction — `Word_Frequency.py`

Edit `csv_path` to point to your reviews CSV.

```bash
python Word_Frequency.py
```

Prints the top 20 terms and bigrams by TF-IDF score to the console.

---

### 5. Keyphrase Classification — `Word_RAKE.py`

Edit `csv_path` to point to your reviews CSV. Optionally tune `ux_seeds`, `arch_seeds`, `SEMANTIC_WEIGHT`, `FREQUENCY_WEIGHT`, and `THRESHOLD`.

```bash
python Word_RAKE.py
```

Prints the top 10 UX phrases and top 10 Architecture phrases with weighted scores.

---

## 🧠 How the Pipeline Works

```
Google Maps
    │
    ▼
Reveiw_scraper.py ──► reviews CSV
    │
    ├──► Review_Count.py     → keyword × rating pivot (Excel)
    ├──► Sentiment_Luke.py   → per-review sentiment labels (Excel)
    ├──► Word_Frequency.py   → dominant terms by TF-IDF (console)
    └──► Word_RAKE.py        → UX vs. Architecture keyphrases (console)
```

**Scraper internals:**
- Navigates via search URL (avoids fragile search box selectors)
- Detects consent/CAPTCHA screens and pauses for manual resolution if needed
- Scrolls the Reviews container, expanding truncated reviews before extraction
- Extracts via in-page JavaScript; deduplicates by `review_id` or fallback key
- Fully resumable — appends to existing CSV on rerun

---

## 🔍 Example Insights

- **Parking and seating** consistently rank as top experience drivers across venues
- **Operational friction** (staff, navigation, security) clusters in specific time periods
- Overall sentiment skews positive, but targeted pain points disproportionately shape perception

---

## 🛠️ Troubleshooting

| Issue | Cause / Fix |
|---|---|
| `FAST FAIL: review text extraction is mostly empty` | Layout change or blocked page — check `blocked_*.png/html` in the output folder |
| No new reviews found | Scraper stops after `NO_GROWTH_LIMIT` scrolls with no new data |
| Wrong venue loaded | Set `PLACE_URL` to a direct `/maps/place/...` URL |
| Existing CSV schema mismatch | `Reveiw_scraper.py` will throw an error — rename or delete the old CSV before resuming |

---

## 🧑‍💼 About

**Mahdi Afkhami, PhD**  
Design Researcher | UX Strategist | Data Analytics  
[LinkedIn](https://www.linkedin.com/in/mahdi-afkhamiaghda/)
