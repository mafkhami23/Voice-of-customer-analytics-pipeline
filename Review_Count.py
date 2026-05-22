import pandas as pd
import re
import os
from collections import defaultdict

# ==============================
# 1. Load your CSV
# ==============================
csv_path = r"C:\Users\13653\OneDrive - Corgan\Python_Codes\Selenium\margot_and_bill_winspear_opera_house_reviews 1.csv"
df = pd.read_csv(csv_path)

# Standardize rating
df['rating'] = df['rating'].str.strip().str.lower()  # e.g., "5 stars"

# ==============================
# 2. Define keywords to track
# ==============================
keywords = ['seat', 'parking', 'staff', 'acoustics', 'website', 
            'lobby', 'security','experience', 'sound','navigation']

# ==============================
# 3. Count keywords per rating
# ==============================
counts = {kw: defaultdict(int) for kw in keywords}

for _, row in df.iterrows():
    text = str(row['review_text']).lower()
    rating = row['rating']
    
    for kw in keywords:
        if re.search(r'\b' + re.escape(kw) + r'\b', text):
            counts[kw][rating] += 1

# ==============================
# 4. Convert to DataFrame
# ==============================
rows = []
for kw, rating_dict in counts.items():
    row = {'keyword': kw}
    for r in ['1 star', '2 stars', '3 stars', '4 stars', '5 stars']:
        row[r] = rating_dict.get(r, 0)
    rows.append(row)

pivot_df = pd.DataFrame(rows)

# ==============================
# 5. Save to XLSX
# ==============================
filename = input("Name of the building: ")
base_dir = r"C:\Users\13653\OneDrive - Corgan\Python_Codes\Selenium"
output_path = os.path.join(base_dir, f"{filename}_KeywordCount.xlsx")
pivot_df.to_excel(output_path, index=False)

print(f"Pivoted keyword rating counts saved to: {output_path}")
