import hashlib
from simhash import Simhash
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

SIMHASH_THRESHOLD = 20
TFIDF_THRESHOLD = 0.2

def compute_url_hash(url: str) -> str:
    return hashlib.sha256(url.strip().lower().encode()).hexdigest()

def compute_title_simhash(title: str) -> str:
    return str(Simhash(title.lower().split()).value)

def is_simhash_duplicate(new_hash: str, existing_hashes: list[str], threshold: int = SIMHASH_THRESHOLD) -> bool:
    new_val = int(new_hash)
    for existing in existing_hashes:
        existing_val = int(existing)
        xor = new_val ^ existing_val
        hamming_distance = bin(xor).count('1')
        if hamming_distance <= threshold:
            return True
    return False

def compute_tfidf_similarity(text: str, existing_texts: list[str]) -> float:
    # Accepts any text (e.g. title + content excerpt), not just headlines.
    if not existing_texts:
        return 0.0
    all_texts = existing_texts + [text]
    try:
        vectorizer = TfidfVectorizer(
            stop_words='english',
            max_features=1000,
            ngram_range=(1, 2)
        )
        tfidf_matrix = vectorizer.fit_transform(all_texts)
        new_vector = tfidf_matrix[-1]
        existing_vectors = tfidf_matrix[:-1]
        similarities = cosine_similarity(new_vector, existing_vectors)
        return float(similarities.max())
    except Exception:
        return 0.0
