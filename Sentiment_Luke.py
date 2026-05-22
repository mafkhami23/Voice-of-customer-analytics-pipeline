"""
Sentiment Analysis of Review Text Using VADER

This script reads a CSV file containing text reviews, applies
VADER sentiment analysis to classify each review as:
    - Positive
    - Neutral
    - Negative

Key Features:
1. Row-safe: Each row receives exactly one label.
2. Neutral is explicit: Empty or ambiguous text is labeled Neutral.
3. VADER-based: Uses NLTK's pre-trained sentiment analyzer for social/review text.
4. Extensible: Easy to switch columns, thresholds, or output formats.
"""

# ==============================
# 1. Import required libraries
# ==============================
import pandas as pd
import nltk
from nltk.sentiment import SentimentIntensityAnalyzer

# ==============================
# 2. Ensure VADER lexicon is available
# ==============================
# VADER (Valence Aware Dictionary and sEntiment Reasoner) is a lexicon and
# rule-based sentiment analysis tool specifically tuned for short social
# media text, reviews, or feedback.
try:
    nltk.data.find("sentiment/vader_lexicon.zip")
except LookupError:
    nltk.download("vader_lexicon")  # Download if missing

sia = SentimentIntensityAnalyzer()  # Initialize the analyzer

# ==============================
# 3. Load your CSV data
# ==============================
# Update this path to your own CSV file containing reviews
csv_path = r'C:\Users\13653\OneDrive - Corgan\Python_Codes\Selenium\margot_and_bill_winspear_opera_house_reviews 1.csv'
df = pd.read_csv(csv_path)

# ==============================
# 4. Define the row-level sentiment classifier
# ==============================
def classify_sentiment(text):
    """
    Classify text into Positive, Neutral, or Negative using VADER.

    Args:
        text (str): Review or comment text.

    Returns:
        str: One of "Positive", "Neutral", or "Negative".

    Notes:
    - Empty or NaN text is classified as Neutral.
    - VADER returns a 'compound' score between -1 (most negative) 
      and +1 (most positive).
    - Thresholds for classification are standard VADER guidelines:
        * Negative: compound <= -0.05
        * Positive: compound >= +0.05
        * Neutral: -0.05 < compound < +0.05
      These thresholds are widely used in academic literature and
      industry practice for short, informal text.
    """
    if pd.isna(text) or str(text).strip() == "":
        return "Neutral"  # Empty text is neutral

    score = sia.polarity_scores(str(text))["compound"]

    if score <= -0.05:
        return "Negative"
    elif score >= 0.05:
        return "Positive"
    else:
        return "Neutral"

# ==============================
# 5. Apply the classifier to your target column
# ==============================
# Change this to the column in your CSV that contains review text
COLUMN_TO_CHECK = "review_text"

# Apply row by row
df["sentiment"] = df[COLUMN_TO_CHECK].apply(classify_sentiment)

# ==============================
# 6. Count results and validate
# ==============================
counts = df["sentiment"].value_counts()

print("Sentiment Summary (row-safe):")
print(counts)

print("\nTotal rows in file:", len(df))
print("Sum of sentiment labels:", counts.sum())
# The sum of counts must equal total rows, ensuring no row is double-counted.

# ==============================
# 7. Optional: Save results
# ==============================
# Export the DataFrame with sentiment labels for reporting or further analysis
# df.to_csv("sentiment_results.csv", index=False)
filename = input("Name of the building: ")
#filename = "Winspear"
df.to_excel(f"{filename}_sentiment_results.xlsx", index=False)

# ==============================
# 8. Tutorial / Notes
# ==============================
"""
How VADER works:
- It uses a lexicon of words with sentiment scores and rules for
  handling punctuation, capitalization, and negation.
- Returns a dictionary of scores: 'neg', 'neu', 'pos', 'compound'
- 'compound' is a normalized score between -1 and +1 summarizing overall sentiment

Thresholds:
- The thresholds (-0.05, 0.05) are standard and suggested by the authors
  of VADER. They create a neutral zone for slightly positive or negative
  text where the sentiment is ambiguous.

Why row-safe:
- We apply a function per row with .apply()
- Each row returns exactly one label: Positive / Neutral / Negative
- The sum of counts always equals the number of rows in the dataset

Customizing:
- Columns: Change COLUMN_TO_CHECK to analyze other columns
- Thresholds: Adjust the -0.05 / 0.05 boundaries if you want
  more aggressive classification
- Hybrid approach: Combine VADER sentiment with keyword intent
  (like "would not recommend") for business-specific decisions
"""
