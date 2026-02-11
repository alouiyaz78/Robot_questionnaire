from typing import List


def normalize_text(text: str) -> str:
    # simple cleanup
    text = text.replace("\r", "\n")
    # remove too many blank lines
    lines = [ln.strip() for ln in text.split("\n")]
    out = []
    blank = 0
    for ln in lines:
        if not ln:
            blank += 1
            if blank <= 1:
                out.append("")
        else:
            blank = 0
            out.append(ln)
    return "\n".join(out).strip()


def chunk_text(text: str, max_chars: int = 6000, overlap: int = 400) -> List[str]:
    """
    Chunking simple par caractères (robuste, rapide).
    max_chars ~ taille gérable pour un prompt.
    """
    text = normalize_text(text)
    if not text:
        return []

    chunks = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + max_chars, n)
        chunk = text[start:end]
        chunks.append(chunk)
        if end == n:
            break
        start = max(0, end - overlap)
    return chunks
