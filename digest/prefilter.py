import re
import unicodedata

__all__ = ["language_ok"]


def _is_vi_char(ch: str) -> bool:
    name = unicodedata.name(ch, "")
    if any(m in name for m in ("HORN", "HOOK ABOVE", "DOT BELOW", "BREVE AND", "CIRCUMFLEX AND")):
        return True
    if ch in "đĐ":
        return True
    return False


VI_WORDS: set[str] = {
    "khong", "không", "nhung", "những", "duoc", "được", "nguoi", "người",
    "tieng", "tiếng", "viet", "việt", "tiet", "tiết", "kiem", "kiệm",
}

EN_STOPWORDS: set[str] = {
    "a", "an", "the", "in", "on", "at", "to", "for", "of", "with", "by",
    "from", "is", "are", "was", "were", "be", "been", "being", "have",
    "has", "had", "do", "does", "did", "can", "could", "will", "would",
    "should", "it", "this", "that", "these", "those", "my", "your", "his",
    "her", "its", "our", "their", "what", "which", "who", "whom",
    "how", "why", "when", "where", "and", "or", "but", "if",
    "so", "no", "not", "as", "out", "up", "down", "about", "into",
    "over", "after", "anyone", "tried", "yet", "new", "just", "all",
    "any", "some", "more", "you", "we", "they", "i", "me",
}

FOREIGN_WORDS: set[str] = {
    # Spanish
    "el", "la", "los", "las", "un", "una", "unos", "unas", "que", "qué",
    "de", "del", "al", "para", "por", "con", "es", "son", "como", "cómo",
    "su", "sus", "hay", "hace", "te", "se", "lo", "este", "esta", "pero",
    "sea", "desafío", "plataformas", "satisfactorio", "aprender", "programar",
    "empresas", "contraten", "actualmente",
    # French
    "le", "les", "des", "du", "ce", "cet", "cette", "ces", "est", "sont",
    "dans", "pour", "sur", "avec", "nous", "vous", "ils", "elles", "va",
    "ont", "pas", "ne", "au", "aux", "remplacer", "artificielle",
    # German
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer",
    "eines", "einem", "einen", "und", "von", "zu", "mit", "auf", "für",
    "ist", "sind", "nicht", "im", "hat", "mich", "dich", "sich", "wie",
    "umgehauen",
    # Swedish
    "och", "det", "att", "jag", "hon", "som", "han", "på", "den", "med",
    "var", "sig", "för", "inte", "till", "av", "om", "ett", "när", "fick",
    "du", "ditt", "dina", "första", "jobb", "inom",
    # Polish
    "jakie", "jaki", "jaka", "czujniki", "temperatury", "wilgotności",
    "polecasz", "nie", "jest", "się", "dla", "jak",
}

FOREIGN_DIACRITICS: set[str] = {
    "ä", "ö", "ü", "ß", "å", "ą", "ć", "ę", "ł", "ń", "ś", "ź", "ż",
    "ñ", "ç",
}


def language_ok(title: str) -> bool:
    if not title or not title.strip():
        return True

    # 1. Reject non-Latin letters
    for ch in title:
        if unicodedata.category(ch).startswith("L"):
            name = unicodedata.name(ch, "")
            if not name.startswith("LATIN"):
                return False

    # 2. Check Vietnamese diacritics
    if any(_is_vi_char(ch) for ch in title):
        return True

    # 3. Spanish inverted punctuation
    if "¿" in title or "¡" in title:
        return False

    # 4. Word extraction
    words = [w.lower() for w in re.findall(r"[^\W\d_]+", title)]
    if not words:
        return True

    if any(w in VI_WORDS for w in words):
        return True

    en_count = sum(1 for w in words if w in EN_STOPWORDS)
    foreign_word_count = sum(1 for w in words if w in FOREIGN_WORDS)
    foreign_dia_count = sum(1 for ch in title.lower() if ch in FOREIGN_DIACRITICS)
    foreign_score = foreign_word_count + foreign_dia_count

    if foreign_score > 0 and foreign_score > en_count:
        return False

    return True
