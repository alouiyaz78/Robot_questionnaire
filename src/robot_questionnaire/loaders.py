import json
import os
from typing import List
import PyPDF2

try:
    import docx
except ImportError:
    docx = None


SUPPORTED_EXTS = {".pdf", ".txt", ".docx", ".py", ".ipynb"}


def list_files(inputs: List[str]) -> List[str]:
    files = []
    for p in inputs:
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                for n in names:
                    ext = os.path.splitext(n)[1].lower()
                    if ext in SUPPORTED_EXTS:
                        files.append(os.path.join(root, n))
        elif os.path.isfile(p):
            ext = os.path.splitext(p)[1].lower()
            if ext in SUPPORTED_EXTS:
                files.append(p)

    seen = set()
    out = []
    for f in files:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def read_pdf(path: str) -> str:
    txt = ""
    with open(path, "rb") as f:
        r = PyPDF2.PdfReader(f)
        for page in r.pages:
            txt += (page.extract_text() or "") + "\n"
    return txt


def read_txt(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read() + "\n"


def read_docx(path: str) -> str:
    if docx is None:
        raise RuntimeError("python-docx non installé. Fais: poetry add python-docx")
    d = docx.Document(path)
    return "\n".join(p.text for p in d.paragraphs) + "\n"


def read_py(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read() + "\n"


def read_ipynb(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        nb = json.load(f)

    texts = []
    for cell in nb.get("cells", []):
        source = cell.get("source", [])
        if isinstance(source, list):
            texts.append("".join(source))
        elif isinstance(source, str):
            texts.append(source)

    return "\n\n".join(texts) + "\n"


def read_file(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return read_pdf(path)
    if ext == ".txt":
        return read_txt(path)
    if ext == ".docx":
        return read_docx(path)
    if ext == ".py":
        return read_py(path)
    if ext == ".ipynb":
        return read_ipynb(path)
    return ""