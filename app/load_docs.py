

import glob
import os
from pypdf import PdfReader
import logging

logger = logging.getLogger("factory-agent")
SOP_DOCS_DIR = "../docs"  # folder of SOP PDFs, filename ~ process name

# --- Simple in-memory SOP index (no vector DB, just text + filenames) ---
_sop_cache: dict[str, str] = {}


def _load_sop_index() -> dict[str, str]:
    """Lazily load and cache text of every SOP pdf in SOP_DOCS_DIR."""
    if _sop_cache:
        return _sop_cache

    print(f"Loading SOP index from {SOP_DOCS_DIR}...")
    for path in glob.glob(os.path.join(SOP_DOCS_DIR, "*.pdf")):
        print(path)
        name = os.path.splitext(os.path.basename(path))[0]
        print(name)
        try:
            reader = PdfReader(path)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            _sop_cache[name.lower()] = text
        except Exception as e:
            logger.warning(f"Failed to read SOP {path}: {e}")
    return _sop_cache

_load_sop_index()  # Load SOP index on module import