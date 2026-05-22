"""
AI-driven Dominant Word Extraction for UX and Architecture Reviews

Features:
- Fully row-safe (handles NaN / non-string review entries)
- TF-IDF extraction (important words and bigrams)
- RAKE keyphrase extraction (important phrases)
- No manual keyword lists required
"""

import pandas as pd
import re
import nltk
from sklearn.feature_extraction.text import TfidfVectorizer
from rake_nltk import Rake

# ==============================
# 1. Load CSV
# ==============================
csv_path = r'C:\Users\13653\OneDrive - Corgan\Python_Codes\Selenium\margot_and_bill_winspear_opera_house_reviews 1.csv'
df = pd.read_csv(csv_path)

# ==============================
# 2. Ensure NLTK stopwords
# ==============================
try:
    nltk.data.find('corpora/stopwords')
except LookupError:
    nltk.download('stopwords')

stop_words = set(nltk.corpus.stopwords.words('english'))
stop_words_list = list(stop_words)  # Must be a list for sklearn and RAKE

# ==============================
# 3. Clean text (row-safe)
# ==============================
def clean_text(text):
    """Lowercase, remove punctuation, remove extra spaces, handle NaN."""
    if pd.isna(text):
        return ""
    text = str(text).lower()
    text = re.sub(r'[^a-z\s]', ' ', text)  # Remove non-alphabetic
    text = re.sub(r'\s+', ' ', text).strip()  # Remove extra spaces
    return text

df['cleaned_text'] = df['review_text'].apply(clean_text)

# ==============================
# 4. TF-IDF extraction
# ==============================
vectorizer = TfidfVectorizer(
    stop_words=stop_words_list,  # Must be a list
    ngram_range=(1,2),           # unigrams + bigrams
    max_features=50              # limit top 50 terms
)

tfidf_matrix = vectorizer.fit_transform(df['cleaned_text'])
feature_names = vectorizer.get_feature_names_out()
scores = tfidf_matrix.sum(axis=0).A1
tfidf_scores = sorted(zip(feature_names, scores), key=lambda x: x[1], reverse=True)

print("Top 20 dominant terms by TF-IDF:")
for term, score in tfidf_scores[:20]:
    print(f"{term}: {score:.4f}")



# ==============================
# 6. Optional: Save results
# ==============================
# df.to_csv("review_analysis.csv", index=False)
# df.to_excel("review_analysis.xlsx", index=False)
