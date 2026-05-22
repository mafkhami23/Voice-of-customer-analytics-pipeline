"""
AI-driven Domain-Specific Keyphrase Extraction
with Frequency Weighting

- Row-safe (handles NaN / non-string entries)
- RAKE keyphrase extraction
- Deduplication
- Frequency weighting
- Semantic embedding classification into:
    1. User Experience (UX)
    2. Architecture
- Top 10 unique phrases per category
"""

import pandas as pd
import re
import nltk
from rake_nltk import Rake
from sentence_transformers import SentenceTransformer, util
from collections import Counter, defaultdict
import numpy as np

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
stop_words_list = list(stop_words)

# ==============================
# 3. Clean text (row-safe)
# ==============================
def clean_text(text):
    if pd.isna(text):
        return ""
    text = str(text).lower()
    text = re.sub(r'[^a-z\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text

df['cleaned_text'] = df['review_text'].apply(clean_text)

# ==============================
# 4. RAKE keyphrase extraction
# ==============================
text_list = df['cleaned_text'].tolist()

r = Rake(
    stopwords=stop_words_list,
    min_length=2,     # avoid single-word dominance
    max_length=4
)

r.extract_keywords_from_sentences(text_list)

# All phrases (with repetition)
raw_phrases = r.get_ranked_phrases()

# ==============================
# 5. Frequency weighting
# ==============================
# Count how often each phrase appears
phrase_freq = Counter(raw_phrases)

# Normalize frequencies (0–1)
max_freq = max(phrase_freq.values())
phrase_freq_norm = {
    phrase: freq / max_freq
    for phrase, freq in phrase_freq.items()
}

# Deduplicate phrases (preserve order)
unique_phrases = list(dict.fromkeys(raw_phrases))

# ==============================
# 6. Semantic filtering using embeddings
# ==============================
model = SentenceTransformer('all-MiniLM-L6-v2')

ux_seeds = [
    "user experience", "interface", "navigation", "workflow",
    "usability", "interaction", "parking",
    "staff", "security", "overall experience"
]

arch_seeds = [
    "architecture", "space", "layout", "flow",
    "environment", "amenities", "circulation",
    "seating", "auditorium"
]

ux_embedding = model.encode(ux_seeds, convert_to_tensor=True)
arch_embedding = model.encode(arch_seeds, convert_to_tensor=True)

phrase_embeddings = model.encode(unique_phrases, convert_to_tensor=True)

ux_scores = util.cos_sim(phrase_embeddings, ux_embedding).max(dim=1).values.cpu().numpy()
arch_scores = util.cos_sim(phrase_embeddings, arch_embedding).max(dim=1).values.cpu().numpy()

# ==============================
# 7. Combine semantic score + frequency
# ==============================
SEMANTIC_WEIGHT = 0.7
FREQUENCY_WEIGHT = 0.3
THRESHOLD = 0.35

ux_best = defaultdict(float)
arch_best = defaultdict(float)

for i, phrase in enumerate(unique_phrases):
    semantic_ux = ux_scores[i]
    semantic_arch = arch_scores[i]
    freq_score = phrase_freq_norm.get(phrase, 0)

    # Final weighted score
    ux_final = SEMANTIC_WEIGHT * semantic_ux + FREQUENCY_WEIGHT * freq_score
    arch_final = SEMANTIC_WEIGHT * semantic_arch + FREQUENCY_WEIGHT * freq_score

    if ux_final >= THRESHOLD and ux_final >= arch_final:
        ux_best[phrase] = max(ux_best[phrase], ux_final)

    elif arch_final >= THRESHOLD and arch_final > ux_final:
        arch_best[phrase] = max(arch_best[phrase], arch_final)

# ==============================
# 8. Top 10 unique phrases
# ==============================
ux_phrases = sorted(ux_best.items(), key=lambda x: x[1], reverse=True)[:10]
arch_phrases = sorted(arch_best.items(), key=lambda x: x[1], reverse=True)[:10]

# ==============================
# 9. Output results
# ==============================
print("Top 10 User Experience Phrases:")
for phrase, score in ux_phrases:
    print(f"{phrase} (weighted score: {score:.3f})")

print("\nTop 10 Architecture Phrases:")
for phrase, score in arch_phrases:
    print(f"{phrase} (weighted score: {score:.3f})")
