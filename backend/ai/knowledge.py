import re
from collections import Counter

STOPWORDS = set('the a an and or but if then than for from with into of to in on at by is are was were be been being this that these those as it its their our your you we they he she his her have has had do does did not no can could should would may might must will shall about over under after before during through within'.split())

def normalize(text):
    return [w for w in re.findall(r"[a-zA-Z0-9_'-]+", (text or '').lower()) if w not in STOPWORDS and len(w) > 1]

def chunk_text(text, size=1800, overlap=250):
    text = (text or '').strip()
    if not text:
        return []
    chunks=[]
    start=0
    while start < len(text):
        end=min(len(text), start+size)
        if end < len(text):
            boundary=max(text.rfind('\n', start, end), text.rfind('. ', start, end))
            if boundary > start + size//2:
                end=boundary+1
        part=text[start:end].strip()
        if part:
            chunks.append(part)
        if end >= len(text): break
        start=max(0, end-overlap)
    return chunks

def rank_chunks(chunks, query, limit=6):
    q=Counter(normalize(query))
    if not q: return []
    scored=[]
    for chunk in chunks:
        words=Counter(normalize(chunk.content))
        overlap=sum(min(q[k], words[k]) for k in q)
        if not overlap: continue
        phrase_bonus=1.5 if query.lower().strip() in chunk.content.lower() else 0
        score=overlap/(sum(words.values())**0.35 or 1)+phrase_bonus
        scored.append((score, chunk))
    scored.sort(key=lambda x:(x[0], x[1].id), reverse=True)
    return [(score, chunk) for score, chunk in scored[:limit]]
