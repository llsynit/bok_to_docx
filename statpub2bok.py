# IMPORTS
# =======

from __future__     import annotations
from os             import listdir, path, makedirs
from shutil         import copyfile, rmtree, copy2
from logging        import getLogger, INFO, DEBUG, FileHandler, StreamHandler, Formatter, WARNING, ERROR
from argparse       import ArgumentParser, Namespace
from bs4            import BeautifulSoup, NavigableString, Comment, Tag
from bs4.element    import CData
from datetime       import datetime
from json           import load
from copy           import deepcopy
from typing         import Optional, Union, Iterable
from types          import SimpleNamespace
from cssutils       import css, ser 

import re
import logging # TODO: remove, and use particular methods and classes

# STATIC VARIABLES
# ================

STATIC_DIR = path.join(path.dirname(path.abspath(__file__)), 'static')
OUTPUT_DIR = path.join(path.dirname(path.abspath(__file__)), 'output')
STYLESHEET = 'bok.css'  # Relative to the XHTML file

LANGUAGES = {
    'nn': 'Nynorsk',
    'nb': 'Bokmål',
    'en': 'Engelsk',
    'de': 'Tysk',
    'fr': 'Fransk',
    'es': 'Spansk',
    'it': 'Italiensk',
    }

KVILE_BLUE_HEX          = "#003366"
SMALL_P_LENGTH          = 300           # TODO: check length
EMPTY                   = 'EMPTY_LINE'  # TODO: remove
TASK_FILL_BLANK         = '....'    
TASK_FILL_BLANK_SINGLE  = '_'
TASK_FILL_BOX           = '[]'
OPENING_QUOTES          = ['"', '“', '”', '„', '‚', '‘']
CLOSING_QUOTES          = ['"', '”', '’', '”', '»']
HEADING_PUNCTUATION     = ['.', '?', ':', ';', '!', '…']
MATH_OPERATORS          = ["+", "-", "*", "/", "=", "%", "^", "<", ">", "<=", ">="]
MATH_OPERATORS_Q        = ["\\+", "rarr", "=", "\\*", "/", "-"]
MATH_CHEMISTRY_PATTERN  = re.compile(r'"\s*([\w\s"_]+)\s*([{}])\s*([\w\s"_]+)\s*"'.format("|".join(MATH_OPERATORS_Q)))
APOSTROPHE_PATTERN      = re.compile(r"\b[a-zA-Z]’[a-zA-Z]", re.UNICODE)
NORWEGIAN_UNITS         = [
    "cm", "mm", "m", "km",          # Length
    "g", "kg", "mg", "tonn",        # Weight
    "l", "dl", "cl", "ml",          # Volume
    "°C", "°F", "%",                # Temperature & percentage
    "s", "min", "t", "dager", "år"  # Time
]
MATH_SIGNS              = {
        '→': '->',
        '←': '<-',
        '½': '1/2',
        '↉': '0/3',
        '⅓': '1/3',
        '⅔': '2/3',
        '¼': '1/4',
        '¾': '3/4',
        '⅕': '1/5',
        '⅖': '2/5',
        '⅗': '3/5',
        '⅘': '4/5',
        '⅙': '1/6',
        '⅚': '5/6',
        '⅐': '1/7',
        '⅛': '1/8',
        '⅜': '3/8',
        '⅝': '5/8',
        '⅞': '7/8',
        '⅑': '1/9',
        '⅒': '1/10',
        '⅟': '1/',
        }
MATH_SIGNS_PATTERN      = re.compile('|'.join(re.escape(key) for key in MATH_SIGNS.keys()))
INDEXES                 = { # TODO: move to bok_to_docx
        'sup': '^',
        'sub': '\\'
        }
VALID_IPA_PATTERN       = re.compile(r'^[ˈˌ`ʰːa-zA-Zæøåŋðθɔɪʊɛʌʃʒɑɨɯɹɾɤɻɜɝɞɡɓɗʈɖɟɢʡʔɕʑɥʜʢɸβθðʃʒɕʑçʝxɣχʁħʕɬɮʋɹɻjɰlɭʎʟ̥ʰʷ̪̬̹̜̤̰̥̩̯˞ˠˤˡⁿˡʼ]+$', re.UNICODE)
IPA_REGEX               = re.compile(r'\[([^\]]+)\]')
EMOJIS_FILE             = 'emojis.json'
EMOJIS                  = load(open(path.join(STATIC_DIR, EMOJIS_FILE)))
GREEK_LETTERS = { # TODO: make json-file
        'Α': '`A',
        '𝛼': '`a',
        'Β': '`B',
        '𝛽': '`b',
        'Γ': '`G',
        '𝛾': '`g',
        'Δ': '`D',
        '𝛿': '`d',
        'Ε': '`E',
        '𝜖': '`e',
        'Ζ': '`Z',
        '𝜁': '`z',
        'Η': '`H',
        '𝜂': '`h',
        'Θ': '`Q',
        '𝜃': '`q',
        'Ι': '`I',
        '𝜄': '`i',
        'Κ': '`K',
        '𝜅': '`k',
        'Λ': '`L',
        '𝜆': '`l',
        'Μ': '`M',
        '𝜇': '`m',
        'Ν': '`N',
        '𝜈': '`n',
        'Ξ': '`X',
        'ξ': '`x',
        'Ο': '`O',
        '𝜊': '`o',
        'Π': '`P',
        '𝜋': 'pi',
        'Ρ': '`R',
        '𝜌': '`r',
        'Σ': '`S',
        '𝜎': '`s',
        'Τ': '`T',
        '𝜏': '`t',
        'Υ': '`U',
        '𝜐': '`u',
        'Φ': '`F',
        '𝜙': '`f',
        'Χ': '`C',
        '𝜒': '`c',
        'Ψ': '`Y',
        '𝜓': '`y',
        'Ω': '`W',
        '𝜔': '`w',
        }
GREEK_TO_LATIN          = {
        'Α': 'A',
        'Β': 'B', 
        'Γ': 'G', 
        'Δ': 'D', 
        'Ε': 'E', 
        'Ζ': 'Z',
        'Η': 'H',
        'Θ': 'Th',
        'Ι': 'I',
        'Κ': 'K',
        'Λ': 'L',
        'Μ': 'M',
        'Ν': 'N',
        'Ξ': 'X',
        'Ο': 'O',
        'Π': 'P',
        'Ρ': 'R',
        'Σ': 'S',
        'Τ': 'T',
        'Υ': 'Y',
        'Φ': 'F',
        'Χ': 'Ch',
        'Ψ': 'Ps',
        'Ω': 'O',
        'α': 'a',
        'β': 'b',
        'γ': 'g',
        'δ': 'd',
        'ε': 'e',
        'ζ': 'z',
        'η': 'h',
        'θ': 'th',
        'ι': 'i',
        'κ': 'k',
        'λ': 'l',
        'μ': 'm',
        'ν': 'n',
        'ξ': 'x',
        'ο': 'o',
        'π': 'p',
        'ρ': 'r',
        'σ': 's',
        'τ': 't',
        'υ': 'y',
        'φ': 'f',
        'χ': 'ch',
        'ψ': 'ps',
        'ω': 'o',
}

NOTE = {
        'h': {
            'nb': 'Merknad',
            'nn': 'Merknad'
            },
        'toc': {
            'nb': 'Filen har en klikkbar innholdsfortegnelse som viser TOC_LEVELS nivåer – tilsvarende innholdsfortegnelsen i originalboka.',
            'nn': 'Filen har ei klikkbar innhaldsliste som viser TOC_LEVELS nivåer – tilsvarande innholdsfortegnelsen i originalboka.',
            },
        'headings': {
            'nb': 'xxx innleder overskrifter. Overskriftsnivået vises med tall: xxx1, xxx2 osv.',
            'nn': 'xxx innleier overskrifter. Overskriftsnivået vert vist med tal: xxx1, xxx2 osv.',
            },
        'pages': {
            'nb': '--- innleder sidetallet.',
            'nn': '--- står framfor sidetala.',
            },
        'em': {
            'nb': 'Uthevingstegnet er slik: _. Eksempel: _Uthevet tekst_.',
            'nn': 'Uthevingsteiknet er slik: _. Eksempel: _Denne setninga er utheva._',
            },
        'mv_img': {
            'nb': 'Tekst og bilder kan være flyttet til en annen side for å unngå å dele opp teksten.',
            'nn': 'Tekst og bilete kan være flytta til ei anna side for å unngå å dele opp teksten.',
            },
        'keywords': {
            'nb': 'Ord og uttrykk i margen fungerer i originalboka nesten som en slags undertitler, og derfor står de også i den tilrettelagte boka uthevet rett foran det avsnittet de tilhører, innledet med Stikkord:.',
            'nn': 'Ord og uttrykk i margen fungerer i originalboka nesten som ei slags undertittel, og derfor står dei også i den tilrettelagte boka utheva rett framfor det avsnittet dei høyrer til, innleidd med Stikkord:.',
            },
        'tasks': {
            'nb': 'Oppgaver er markert med >>> og har fått kapittelnummer foran selve oppgavetallet for å lette søkbarheten, f.eks.: >>> 1.1 (Begreper)',
            'nn': 'Oppgåver er markert med >>> og har fått kapittelnummer framfor sjølve oppgåvenummeret for å lette søkbarheita, f.eks.: >>> 1.1 (Omgrep)',
            },
        'colophon': {
            'nb': 'Kolofonen finner du til slutt i denne filen.',
            'nn': 'Kolofonen finn du til slutt i denne fila.',
            },
        'index': {
            'nb': 'Stikkordregister og kildelister er utelatt.',
            'nn': 'Stikkordregister og kjeldelister er utelatne.',
            },
        }

# FUNCTIONS
# =========

# --- Logging ------------------------------------------------------

def configure_logging(verbosity: int) -> None:
    """
    verbosity: 0 -> WARNING, 1 -> INFO, 2+ -> DEBUG
    """
    if verbosity <= 0:
        level = WARNING
    elif verbosity == 1:
        level = INFO
    else:
        level = DEBUG

    root = getLogger()
    root.setLevel(level)

    # Opprett én StreamHandler hvis ingen finnes, ellers oppdater nivå/formatter på eksisterende
    fmt = Formatter('%(asctime)s %(levelname)s [%(name)s] %(message)s',
                            datefmt='%H:%M:%S')

    if not root.handlers:
        h = StreamHandler()
        h.setLevel(level)
        h.setFormatter(fmt)
        root.addHandler(h)
    else:
        for h in root.handlers:
            try:
                h.setLevel(level)
                h.setFormatter(fmt)
            except Exception:
                pass

    # Dempe støy fra tredjepart (skrues bare opp hvis du faktisk ber om DEBUG)
    noisy = ('urllib3', 'pika', 'bs4')
    for n in noisy:
        getLogger(n).setLevel(WARNING if level < DEBUG else INFO)

def _build_args_namespace(
    *,
    input_value: str = "INLINE",
    output: Optional[str] = None,
    mathematics: bool = False,
    science: bool = False,
    verbose: bool = False,
    toc_levels: Optional[int] = None,
    grade: Optional[int] = None,
    p_length: Optional[int] = None,
    link_footnotes: bool = False,
    index: bool = False,
) -> Namespace:
    """
    Lager en argparse.Namespace som matcher parser-argumentene dine,
    slik at vi kan kalle apply_requirements() uten å endre den funksjonen.
    """
    return Namespace(
        input=input_value,         # tilsvarer parser.add_argument('input')
        output=output,             # -o / --output
        mathematics=mathematics,   # -m / --mathematics
        science=science,           # -s / --science
        verbose=verbose,           # -v / --verbose
        toc_levels=toc_levels,     # -t / --toc-levels
        grade=grade,               # -g / --grade
        p_length=p_length,         # -p / --p-length
        link_footnotes=link_footnotes,  # -l / --link_footnotes
        index=index,               # -i / --index
    )


def _make_logger(verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger("statpub_to_bok.apply_requirements")
    if not logger.handlers:
        handler = logging.StreamHandler()
        fmt = logging.Formatter("[%(levelname)s] %(message)s")
        handler.setFormatter(fmt)
        logger.addHandler(handler)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    return logger

# 7.2.2 and 7.2.3
def is_special_number(number_str):
    """
    Detects if a number is a phone number, bank account, birth number, date, or time.
    If so, it should be kept unchanged.
    """
    # Phone numbers: Groups of 2-3 digits with spaces (e.g., "12 34 56 78")
    phone_pattern = re.compile(r'^\d{2,3}( \d{2,3})+$')

    # Bank account numbers: Similar structure, sometimes with 4-digit prefix
    bank_pattern = re.compile(r'^\d{4} \d{2} \d{5}$')

    # Birth numbers: "DDMMYY-XXXXX" or "DD.MM.YYYY"
    birth_pattern = re.compile(r'^\d{6}[- ]\d{5}$|^\d{2}\.\d{2}\.\d{4}$')

    # Date pattern: "DD.MM.YYYY" or "YYYY-MM-DD"
    date_pattern = re.compile(r'^\d{2}\.\d{2}\.\d{4}$|^\d{4}-\d{2}-\d{2}$')

    # Time pattern: "HH:MM" or "HH:MM:SS"
    time_pattern = re.compile(r'^\d{2}:\d{2}(:\d{2})?$')

    # If the number matches any of these patterns, it should be preserved
    return any(pattern.match(number_str) for pattern in [phone_pattern, bank_pattern, birth_pattern, date_pattern, time_pattern])


def format_number(number_str, grade):
    """
    Format numbers according to school grade rules:
    - GRADE ≤ 7: Use thousands separators for 4+ digit numbers (e.g., "4.300", "13.200").
    - GRADE ≥ 8: Use thousands separators for 5+ digit numbers (4-digit numbers remain unchanged).
    """

    number_str = number_str.strip()

    # 7.2.2 and 7.2.3
    # Check if it's a special number that should be left unchanged
    # TODO: needs to be checked with its context
    '''
    if is_special_number(number_str):
        print(f"Special number: {number_str}")
        return None  # Return None to indicate no modification
    '''

    # Detect if spaces are used as thousands separators
    if " " in number_str:
        integer_part = number_str.replace(" ", "")
        decimal_part = None
        decimal_separator = ''
    elif ',' in number_str:
        parts = number_str.rsplit(',', 1)  # Split only at the last comma
        integer_part, decimal_part = parts if len(parts) > 1 else (parts[0], None)
        decimal_separator = ','
    elif '.' in number_str and number_str.count('.') > 1:
        return number_str  # Likely an ambiguous case; do not modify
    elif '.' in number_str:
        parts = number_str.rsplit('.', 1)  # Split only at the last dot
        integer_part, decimal_part = parts if len(parts) > 1 else (parts[0], None)
        decimal_separator = '.'
    else:
        integer_part, decimal_part = number_str, None
        decimal_separator = ''

    num_length = len(integer_part.replace(' ', ''))

    if grade <= 7:  # Barneskole (4+ digits get a thousands separator)
        if num_length >= 4:
            integer_part = f"{int(integer_part):,}".replace(",", ".")
    else:  # Ungdomsskole / Videregående (5+ digits get a thousands separator)
        if num_length >= 5:
            try:
                integer_part = f"{int(integer_part):,}".replace(",", ".")
            except ValueError: # TODO: fix
                return number_str
        elif num_length == 4:
            integer_part = integer_part  # Keep 4-digit numbers as is

    # Reconstruct the number
    formatted_number = integer_part
    if decimal_part:
        if len(decimal_part) > 3:
            decimal_part = '.'.join([decimal_part[i:i+3] for i in range(0, len(decimal_part), 3)])
        formatted_number += decimal_separator + decimal_part

    return formatted_number if formatted_number != number_str else None  # Return None if unchanged

# 7.4
def convert_quotes(text):
    # TODO: grocer's apostrophe
    """
    Converts various types of quotation marks:
    - «...» for main quotations.
    - "..." for nested quotations inside «...».
    - Ensures punctuation remains inside quotes (e.g., «Hello!» instead of «Hello»!).
    """
    # Skip processing if already uses « and »
    if '«' in text or '»' in text:
        return text

    # Step 1: Replace all known opening quotes with «
    text = re.sub(r'(^|\s)[“”„‚‘"]+', r'\1«', text)  # Normalize all opening quotes

    # Step 2: Replace all closing quotes with » (including when followed by punctuation)
    text = re.sub(r'([^\s])"([.!?,;:]?)', r'\1»\2', text)  # Handles `"Hello!"` → `«Hello!»`

    # Step 3: Ensure nested quotes inside «...» use straight double quotes ("...")
    text = re.sub(r'«([^«»]*)‘([^«»]*)’([^«»]*)»', r'«\1"\2"\3»', text)  # Converts ‘...’ to "..."
    text = re.sub(r'«([^«»]*)“([^«»]*)”([^«»]*)»', r'«\1"\2"\3»', text)  # Converts “...” to "..."

    # Step 4: Preserve apostrophes in contractions
    text = re.sub(r'\b(\w)»(\w)\b', r"\1’\2", text)  # Restores apostrophes where needed

    return text

def is_valid_ipa(text):
    """
    Checks if the given text is a valid IPA phonetic transcription.
    - Ensures only IPA symbols are used.
    - Rejects numbers, large figures, and extra punctuation.
    """
    cleaned_text = text.strip().replace(",", "").replace(".", "").replace("–", "")

    # Ensure it's NOT a number
    if cleaned_text.replace(",", "").replace(".", "").isdigit():
        return False  # Skip numerical values

    if " " in cleaned_text:  # Allow multi-word IPA transcriptions only if each word is valid
        words = cleaned_text.split()
        return all(VALID_IPA_PATTERN.match(word) for word in words)
    return bool(VALID_IPA_PATTERN.match(cleaned_text))

def debug_dt_elements(soup):
    for dt in soup.find_all("dt"):
        dt_text = dt.get_text(strip=True)  # Extract text
        matches = IPA_REGEX.findall(dt_text)

def replace_greek_letters(text):
    def replacer(match):
        greek_seq = match.group(0)
        latin_equiv = "".join(GREEK_LETTERS.get(char, char) for char in greek_seq)
        return f"`({latin_equiv})" if len(greek_seq) > 1 else f"`{latin_equiv}"
    
    # Regex to find sequences of Greek letters
    greek_pattern = re.compile(r'[Α-Ωα-ω]+')
    
    return greek_pattern.sub(replacer, text)

def check_expressions_without_dl(element, expressions, dl=None):
    """
    Checks if the parent of a <dl> element (excluding the <dl> itself) contains all the given expressions.

    :param html: The HTML content as a string.
    :param expressions: A list of expressions to check.
    :return: True if all expressions exist in the modified parent, False otherwise.
    """
    if dl:
        dl.extract()  # Remove <dl> temporarily from its parent

    # Get the text content of the parent element (without <dl>)
    text = element.get_text(separator=" ", strip=True).lower()

    # Check if all expressions exist in the modified parent text
    return all(expr.lower() in parent_text for expr in expressions)

def safe_split(element, regex):
    parts = regex.split(element, 1)  # Split at the first occurrence

    if len(parts) == 1:
        return parts[0], None, None  # No match found

    elif len(parts) == 2:
        return parts[0], regex.search(element).group(0), parts[1]  # Extract match manually

    return parts  # Normal case (before, match, after)

def find_production_number(soup):
    if (meta := soup.find('meta', attrs={'name': 'dc:identifier'})) and (content := meta.get('content')):
        return content
    elif (identifier := soup.find('dc:identifier')) and identifier.get_text():
        return identifier.get_text()
    else:
        return 'unknown_production_number'


def find_filename(soup):
    if (title := soup.find('title')) and title.get_text():
        return f'{title.get_text()} {find_production_number(soup)}.xhtml'
    else:
        return f'{find_production_number(soup)}.xhtml'


# Whitespace + "usynlige" tegn (NBSP, zero-width, m.m.)
_WS_RE = re.compile(r'[\s\u00A0\u1680\u2000-\u200B\u200C\u200D\u202F\u205F\u2060\u3000\uFEFF]+')

def previous_text_node(
    node: Union[Tag, NavigableString],
    *,
    allow_whitespace: bool = False,
    exclude_parent_tags: Iterable[str] = ('script', 'style'),
    skip_comments: bool = True,
) -> Optional[NavigableString]:
    """
    Returner nærmeste NavigableString før `node` i dokumentrekkefølge.

    Parametre:
      - allow_whitespace: Hvis False, hopper over tekstnoder som bare er whitespace/
        usynlige tegn (inkl. NBSP og zero-width). Hvis True, returneres også slike.
      - exclude_parent_tags: Hopp over tekst som ligger inne i disse taggene.
      - skip_comments: Hopper over BeautifulSoup-kommentarer.

    Går på tvers av <section> (bruker previous_elements).
    """
    if not isinstance(node, (Tag, NavigableString)):
        return None

    for el in getattr(node, 'previous_elements', []):
        if skip_comments and isinstance(el, Comment):
            continue

        if isinstance(el, NavigableString):
            parent = el.parent
            if isinstance(parent, Tag) and parent.name in exclude_parent_tags:
                continue

            s = str(el)
            if allow_whitespace:
                return el
            # bare returner hvis det faktisk finnes synlig tekst
            if _WS_RE.sub('', s) != '':
                return el
            continue

        # el er en Tag: hopp over containere vi ikke vil ned i
        if isinstance(el, Tag) and el.name in exclude_parent_tags:
            continue

    return None

_WS = r'[\s\u00A0\u1680\u2000-\u200B\u202F\u205F\u3000\uFEFF]'
_PAGE_RE = re.compile(rf'^(?:{_WS})*---(?:{_WS})*\d+(?:{_WS})*$')

def next_text_node(
    node: Union[Tag, NavigableString],
    *,
    allow_whitespace: bool = False,
    exclude_parent_tags: Iterable[str] = ('script', 'style'),
    skip_comments: bool = True,
) -> Optional[NavigableString]:
    if not isinstance(node, (Tag, NavigableString)):
        return None
    for el in getattr(node, 'next_elements', []):
        if skip_comments and isinstance(el, Comment):
            continue

        if isinstance(el, NavigableString):
            parent = el.parent
            if isinstance(parent, Tag) and parent.name in exclude_parent_tags:
                continue

            s = str(el)
            if allow_whitespace:
                return el
            # bare returner hvis det faktisk finnes synlig tekst
            if _WS_RE.sub('', s) != '':
                return el
            continue

        # el er en Tag: hopp over containere vi ikke vil ned i
        if isinstance(el, Tag) and el.name in exclude_parent_tags:
            continue
    return None

_WS = r'[\s\u00A0\u1680\u2000-\u200B\u200C\u200D\u202F\u205F\u2060\u3000\uFEFF]'
_PAGE_RE = re.compile(rf'^(?:{_WS})*---(?:{_WS})*\d+(?:{_WS})*$')

def _nearest_p(node: Union[Tag, NavigableString, None]) -> Optional[Tag]:
    if node is None:
        return None
    if isinstance(node, NavigableString):
        node = node.parent
    if not isinstance(node, Tag):
        return None
    return node if node.name == 'p' else node.find_parent('p')

def is_pagenumber(element: Union[Tag, NavigableString]) -> bool:
    """
    True hvis elementet *ligger i* en <p> hvis tekst er '--- [sidetall]'.
    Aksepterer at element er enten Tag eller NavigableString.
    """
    p = _nearest_p(element)
    if p is None:
        return False
    return bool(_PAGE_RE.fullmatch(p.get_text()))

def _prev_tag_sibling(node: Tag):
    """Finn nærmeste forrige søsken som er et Tag (hopper over whitespace)."""
    sib = node.previous_sibling
    while isinstance(sib, NavigableString) and (str(sib).strip() == ""):
        sib = sib.previous_sibling
    return sib if isinstance(sib, Tag) else None

def _count_table_dimensions(table: Tag):
    """
    Returner (kolonner, rader) for en <table>.
    - Rader = antall <tr> som tilhører denne tabellen (ikke nested).
    - Kolonner = maks sum av (colspan eller 1) per rad (bruker kun direkte <td>/<th> i hver <tr>).
    Fallback: hvis ingen celler, prøv <colgroup>/<col>.
    """
    # Rader: bare <tr> hvis nærmeste foreldretabell er denne tabellen
    trs = [tr for tr in table.find_all('tr') if tr.find_parent('table') is table]
    row_count = len(trs)

    # Kolonner: tell direkte celler i hver <tr>, ta høyeste
    max_cols = 0
    for tr in trs:
        cells = tr.find_all(['td', 'th'], recursive=False)
        colsum = 0
        for cell in cells:
            try:
                colspan = int(cell.get('colspan', 1))
            except (TypeError, ValueError):
                colspan = 1
            colsum += max(1, colspan)
        max_cols = max(max_cols, colsum)

    # Fallback via <colgroup> om tabellen ikke hadde celler
    if max_cols == 0:
        colgroup_cols = len(table.find_all('col'))
        if colgroup_cols:
            max_cols = colgroup_cols

    return max_cols, row_count

def _no_plural(n, singular, plural):
    """Enkel norsk bøyning."""
    return singular if n == 1 else plural

# CONVERT
# =======

def apply_requirements(soup, args, logger):
    logger.info('Converting Statpub to make it with the Statped book standard')
    TOC_LEVELS  = args.toc_levels   if args.toc_levels  else 2
    #GRADE       = args.grade        if args.grade       else 8
    BODY        = soup.body         if soup.find('body')    else soup.new_tag('body') # TODO: make more robust

    if args.grade:
        args.grade = int(args.grade)
    else:
        for keyword in soup('meta', attrs={'name':'dc:subject.keyword'}):
            if 'content' in keyword.attrs and keyword['content'].isdigit():
                args.grade = int(keyword['content'])
                break
    if not args.grade:
        args.grade = 10  # default høyeste nivå
    GRADE = args.grade
    logger.info(f'Using GRADE = {GRADE}')

    metadata = {
            'production_number' : find_production_number(soup), 
            'title'             : title.get_text() if (title := soup.find('title')) else None, # TODO: fix utf-8 bug
            'subtitle'          : subtitle.get_text() if (subtitle := soup.find('meta', attrs={'name': 'dc:title.subTitle'})) else None,
            'authors'           : [author['content'] for author in soup('meta', attrs={'name': 'dc:creator'})],
            'publisher'         : publisher.get_text() if (publisher := soup.find('meta', attrs={'name': 'dc:publisher.original'})) else None,
            'modified'          : meta.get('content') if (meta := soup.find('meta', {'name': 'dcterms:modified'})) else None,
            'language'          : meta.get('content') if (meta := soup.find('meta', {'name': 'dc:language'})) else None,
            'source'            : meta.get('content') if (meta := soup.find('meta', {'name': 'dc:source'})) else None,
            'pages'             : soup(attrs={'epub:type': 'pagebreak'}), 
            'pagenumbers'       : [],
            'p_length'          : args.p_length if args.p_length else SMALL_P_LENGTH,
            'edition'           : edition.get_text() if (edition := soup.find('meta', attrs={'name': 'schema:bookEdition'})) else None,
            'isbn'              : isbn.get_text().split(':')[-1] if (isbn := soup.find('meta', attrs={'name': 'dc:source'})) else None,
    }

    for page in metadata['pages']:
        if 'title' not in page.attrs.keys():
            if 'id' in page.attrs.keys():
                logger.info(f'Metadata: Assigning title to page {page["id"]} - {page["id"].split("-")[-1]}')
                metadata['pagenumbers'].append(page["id"].split("-")[-1])
            else:
                logger.error(f'Page {page} has no title or id')
                page = f'Generated page {metadata["pages"].index(page)}'
        else:
            metadata['pagenumbers'].append(page['title'])

    # Preliminary cleanup
    # ===================

    # Find and extract all comments
    # -----------------------------
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()

    # Book standard
    # =============

    # 4.1.2 Skrifttype
    # ----------------

    logger.info(f'4.1.2 Skrifttype')
    with open(path.join(STATIC_DIR, STYLESHEET), 'r', encoding='utf-8') as f:
        css_content = f.read()
    style_tag = soup.new_tag('style', type='text/css')
    style_tag.string = css_content
    if soup.head:
        soup.head.append(style_tag)
        if (old_css := soup.find('link', attrs={'rel': 'stylesheet'})):
            # TODO: check if old_css is needed
            logger.info(f'Removing old stylesheet link: {old_css}')
            old_css.decompose()


    # 4.2 Filnavn
    # -----------
    # Set in pandoc conversion
    logger.info(f'4.2 Filnavn')
    # Implemented in main and app.py

    # 4.3 De første linjene TODO: check why pandoc removes these
    # ----------------------
    logger.info(f'4.3 De første linjene')
    first_lines = soup.new_tag('section')
    
    # First line
    first_line = soup.new_tag('p')
    if (title := soup.find('title')): 
        first_line.append(f'{title.get_text()}') 
    else:
        first_line.append('Tittel mangler')
    first_lines.append(first_line)

    # Second line
    pagebreaks = BODY(attrs={'epub:type': 'pagebreak'})
    if pagebreaks:
        second_line = soup.new_tag('p')
        if 'aria-label' in pagebreaks[0].attrs:
            # first_page = pagebreaks[0]['aria-label']
            second_line.append(f'Side {pagebreaks[0]["aria-label"]}')
        if 'aria-label' in pagebreaks[-1].attrs:
            second_line.append(f' til {pagebreaks[-1]["aria-label"]}')
        else:
            pass # TODO: check
            #print(pagebreaks[-1])
        first_lines.append(second_line)

    BODY.insert(0, first_lines)

    # 4.4 Merknad #4 TODO: set classes
    # --------------
    # h, toc, pages, em, mv_img, index
    # TODO: check placement

    logger.info(f'4.4 Merknad')
    if (toc := soup.find('section', attrs={'epub:type': 'frontmatter toc'})):
        notice = soup.new_tag('section')
        notice['epub:type'] = 'notice' # TODO
        notice['id'] = 'notice'
       
        # h
        h1 = soup.new_tag('h1')
        h1.string = 'Merknad'
        notice.append(h1)
        
        # toc
        p1 = soup.new_tag('p')
        string = NOTE['toc'][metadata['language']] if metadata['language'] in NOTE['toc'] else NOTE['toc']['nb']
        p1.string = string.replace('TOC_LEVELS', str(TOC_LEVELS))
        notice.append(h1)
      
        # headings
        if GRADE <= 5:   
            p2 = soup.new_tag('p')
            p2.string = NOTE['headings'][metadata['language']] if metadata['language'] in NOTE['headings'] else NOTE['headings']['nb']
            notice.append(p2)

        # pages
        p3 = soup.new_tag('p')
        p3.string = NOTE['pages'][metadata['language']] if metadata['language'] in NOTE['pages'] else NOTE['pages']['nb']
        notice.append(p3)

        # em
        p4 = soup.new_tag('p')
        p4.string = NOTE['em'][metadata['language']] if metadata['language'] in NOTE['em'] else NOTE['em']['nb']
        notice.append(p4)

        # mv_img
        p5 = soup.new_tag('p')
        p5.string = NOTE['mv_img'][metadata['language']] if metadata['language'] in NOTE['mv_img'] else NOTE['mv_img']['nb']
        notice.append(p5)

        # keywords
        p6 = soup.new_tag('p')
        p6.string = NOTE['keywords'][metadata['language']] if metadata['language'] in NOTE['keywords'] else NOTE['keywords']['nb']
        notice.append(p6)

        # tasks
        p7 = soup.new_tag('p')
        p7.string = NOTE['tasks'][metadata['language']] if metadata['language'] in NOTE['tasks'] else NOTE['tasks']['nb']
        notice.append(p7)

        # colophon
        p8 = soup.new_tag('p')
        p8.string = NOTE['colophon'][metadata['language']] if metadata['language'] in NOTE['colophon'] else NOTE['colophon']['nb']
        notice.append(p8)

        # index
        if not args.index:
            p9 = soup.new_tag('p')
            p9.string = NOTE['index'][metadata['language']] if metadata['language'] in NOTE['index'] else NOTE['index']['nb']
            notice.append(p9)

        toc.insert_after(notice)

    # 4.5 Innholdsfortegnelse
    # Moved below

    # 4.6 Hovedinnhold
    # TODO: check placement of notice before content
    logger.info('4.6 Hovedinnhold')
    chapters = BODY('section', attrs={'epub:type': 'bodymatter chapter'})
    for chapter in chapters[::-1]:
        toc.insert_after(chapter)

    # 4.7 Stikkordregister og kildelister
    # Bildekilder utelates.
    logger.info('4.7 Stikkordregister og kildelister')
    if args.index:
        for section in BODY('section', attrs={'epub:type': re.compile(r"(^| )index($| )")}):
            logger.info(f'Removing index section {section["id"]}')
            section.decompose()
    # TODO: Source list
    # TODO: Image list
    image_creds = [
            'Bildekreditering',
            'Bildekrediteringar',
            'Bilder og illustrasjoner'
            ] 
    for section in soup('section', attrs={'epub:type':'backmatter'}):
        if (h := section.find(re.compile('^h[1-6]$'))) and h.get_text().strip() in image_creds:
            logger.info(f'Removing image credits section {section["id"]}')
            section.decompose()

    # 4.8 Stoff fra bokomslaget
    # --------------------------
    # TODO: create strategy: rebuild or retract
    

    # 4.8.1 Deprecated
    '''
    # 4.8.1 Kolofon #8
    # All information is taken from the metadata, except "opplag" and "utgave",
    # which are taken from the colophon.
    logger.info('4.8.1 Kolofon')
    if (colophon := BODY.find('section', attrs={'epub:type': re.compile(r"(^| )colophon($| )")})):
        # Hack until edition and print is fetched to the metadata
        if not metadata['edition']:
            for p in colophon('p'):
                if 'utgave' in p.get_text().lower() and 'opplag' in p.get_text().lower():
                    metadata['edition'] = p.get_text()
        colophon.clear()
        h1 = soup.new_tag('h1')
        h1.string = 'Om boka'
        colophon.append(h1)

        if metadata['title']:
            p = soup.new_tag('p')
            p.string = f'Tittel: {metadata["title"]}'
            colophon.append(p)
            if metadata['subtitle']:
                p.append(NavigableString(f', {metadata["subtitle"]}'))

        if metadata['authors']:
            authors = []
            for author in metadata['authors']:
                if ',' in author:
                    authors.append(f'{author.split(",")[-1].strip()} {author.split(",")[0].strip()}')
                else:
                    authors.append(author)
            p = soup.new_tag('p')
            p.string = f'{", ".join(authors)}'
            colophon.append(p)

        if metadata['language']:
            p = soup.new_tag('p')
            if metadata['language'] in LANGUAGES:
                p.string = f'Språk: {LANGUAGES[metadata["language"]]}'
            else:
                p.string = f'{metadata["language"]}'
            colophon.append(p)

        if metadata['publisher']:
            p = soup.new_tag('p')
            p.string = f'{metadata["publisher"]}'
            colophon.append(p)

        if metadata['isbn']:
            p = soup.new_tag('p')
            p.string = f'ISBN {metadata["isbn"]}'
            colophon.append(p)

        if metadata['production_number']:
            p = soup.new_tag('p')
            p.string = f'Produksjonsnummer {metadata["production_number"]}'
            colophon.append(p)

    '''

    # 4.9 Stoff fra tittelside og kolofon
    logger.info('4.9 Stoff fra tittelside og kolofon')
    # TODO: change name to frontmatter-moved, to accomodate the insertion of the notice in prepare_for_braille
    titlepage_and_colophon_section = soup.new_tag('section')
    titlepage_and_colophon_section['epub:type'] = 'frontmatter titlepage colophon'
    titlepage_section = soup.new_tag('section')
    titlepage_section['epub:type'] = 'frontmatter titlepage'
    h1 = soup.new_tag('h1')
    h1.string = 'Om boka'
    titlepage_section.append(h1)
    if metadata['title']:
        title_p = soup.new_tag('p')
        title_p.string = f'{metadata["title"]}'
        titlepage_section.append(title_p)
    else:
        print('Title missing')
    if metadata['authors']:
        authors = []
        for author in metadata['authors']:
            if ',' in author:
                authors.append(f'{author.split(",")[-1].strip()} {author.split(",")[0].strip()}')
            else:
                authors.append(author)
        title_p.append(NavigableString(f' av {", ".join(authors)}'))
        titlepage_section.append(title_p)
    if metadata['language'] and metadata['language'] in LANGUAGES:
        lang_p = soup.new_tag('p')
        lang_p.string = f'Språk: {LANGUAGES[metadata["language"]]}'
        titlepage_section.append(lang_p)
    publisher = metadata['publisher'] if metadata['publisher'] else 'Ukjent forlag'
    year = metadata['modified'][:4] if metadata['modified'] else 'Ukjent år'
    pubyear_p = soup.new_tag('p')
    pubyear_p.string = f'{publisher}, {year}'
    titlepage_section.append(pubyear_p)
    # TODO: version, edition
    if metadata['edition']:
        edition_p = soup.new_tag('p')
        edition_p.string = f'{metadata["edition"]}' # TODO: edition
        titlepage_section.append(edition_p)
    # TODO: isbn
    if metadata['isbn']:
        isbn_p = soup.new_tag('p')
        isbn_p.string = f'ISBN {metadata["isbn"]}'
        titlepage_section.append(isbn_p)
    if metadata['production_number']:
        prod_p = soup.new_tag('p')
        prod_p.string = f'Produksjonsnummer: {metadata["production_number"]}'
        titlepage_section.append(prod_p)
    titlepage_and_colophon_section.append(titlepage_section)
    soup.body.append(titlepage_and_colophon_section)


    # 4.9.1 Opphavsrett Statped
    # -----------------------
    logger.info('4.9.1 Opphavsrett Statped')
    copyright_text = {
            'Bokmål': [
                'Denne boka er tilrettelagt for elever med synsnedsettelse. Ifølge åndsverkloven kan den bare brukes av personer med nedsatt funksjonsevne. Teksten er tilpasset for lesing med skjermleser og leselist. Kopiering er kun tillatt til eget bruk. Brudd på disse avtalevilkårene, som ulovlig kopiering eller medvirkning til ulovlig kopiering, kan medføre ansvar etter åndsverkloven.',
                'I tillegg gjelder forlagets bestemmelser slik de er beskrevet i originalboka.'],
            'Nynorsk': [
                'Denne boka er lagd til rette for elevar med synssvekking. Ifølgje åndsverklova kan ho berre brukast av personar med nedsett funksjonsevne. Teksten er tilpassa for lesing med skjermlesar og leselist. Det er berre tillate å kopiere til eige bruk. Brot på desse avtalevilkåra, slik som ulovleg kopiering eller medverknad til ulovleg kopiering, kan medføre ansvar etter åndsverklova.',
                'I tillegg gjeld føresegnene frå forlaget slik dei er uttrykte i originalboka.'],
            }

    copyright_section = soup.new_tag('section')
    copyright_section['epub:type'] = 'notice'
    copyright_section['id'] = 'copyright'
    h1 = soup.new_tag('h1') # TODO: check if h1 is correct here
    h1.string = 'Opphavsrett:'
    copyright_section.append(h1)

    if metadata['language'] and metadata['language'] in LANGUAGES and metadata['language'] == 'Nynorsk':
        for element in copyright_text['Nynorsk']:
            p = soup.new_tag('p')
            p.string = element
            copyright_section.append(p)
    else:
        for element in copyright_text['Bokmål']:
            p = soup.new_tag('p')
            p.string = element
            copyright_section.append(p)
    soup.body.append(copyright_section)

    # 4.10 Sluttlinje
    # ---------------
    logger.info('4.10 Sluttlinje')
    last_section = soup.new_tag('section')
    p = soup.new_tag('p')
    p['id'] = 'endline'
    p.string = f':::xxx::: {datetime.now().strftime("%d.%m.%Y")}'
    last_section.append(p)
    soup.body.append(last_section)

    # 4.11 Overskrifter
    # -----------------
    logger.info('4.11 Overskrifter')
    for h in BODY(re.compile('^h[1-6]$')):
        if GRADE <= 3 and (text := h.get_text()) and text[-1] not in HEADING_PUNCTUATION:
            h.append('.')
        if GRADE <= 5:
            h.insert(0, NavigableString(f'xxx{h.name[-1]} '))
    # Hanging indent in css: text-indent: -2en; padding-left: 2en; TODO: check
    # TODO: colours for grade <= 8 ?

    # In docx template file

    # 4.12 Sidetall
    # -------------
    # -> prepare_for_docx
    logger.info('4.12 Sidetall')
    for pagebreak in soup(attrs={'epub:type':'pagebreak'}): #metadata['pages']:
        page_element = pagebreak
        for parent in pagebreak.parents:
            if parent.name == 'p':
                page_element = parent
                break
        page = None
        if 'aria-label' in pagebreak.attrs:
            page = pagebreak.get('aria-label')
        elif 'title' in pagebreak.attrs:
            page = pagebreak.get('title')
        elif 'id' in pagebreak.attrs:
            page = pagebreak.get('id').split('-')[-1]
        if page:
            page_p = soup.new_tag('p')
            page_p.string = f'--- {page}'
            pagebreak.insert_after(page_p)
            page_element.insert_after(page_p)
            if (next_element := page_p.find_next_sibling()):
                if (next_element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6'] or
                    next_element.name == 'section' and next_element.find(re.compile('^h[1-6]$'))):
                    blank_p = soup.new_tag('p')
                    blank_p['class'] = 'blank_line'
                    page_p.insert_before(blank_p)

    # 4.13 Avsnitt
    # ------------
    # -> included in 4.14

    # 4.14 Blank linje
    # ----------------
    # -> end of the method

    # 4.15.1 Mellomrom ved matematiske regnetegn
    # ------------------------------------------
    logger.info('4.15.1 Mellomrom ved matematiske regnetegn - solved in mathml_to_statpedmath_xslt')

    # 4.15.2 Mellomrom ved benevninger
    # --------------------------------
    logger.info('4.15.2 Mellomrom ved benevninger')
    pattern_no_space_before_unit = rf"(\d)({'|'.join(map(re.escape, NORWEGIAN_UNITS))})"

    for element in BODY(string=True):
        text = element.string
        if text:
            text = re.sub(pattern_no_space_before_unit, r"\1 \2", text)
            element.string.replace_with(text)
    # TODO: optimize

    # 4.16 Utheving
    # -------------
    for emphasis in list(BODY.find_all(['em', 'strong'])):
        # Hopp over elementer som ligger inni annen utheving
        if emphasis.find_parent(['em', 'strong']) is not None:
            continue

        text = emphasis.get_text()
        emphasis.replace_with(NavigableString(f'_{text}_'))

    # 4.17 Strukturinformasjon
    # ------------------------
    # Asides
    for ramme in BODY.select('.ramme'):
        if (children := [child for child in ramme.children if not child.get_text().strip() == '']):
            children_tags = [tag for tag in children if isinstance(tag, Tag)]
            start_text = ''
            if ':' in children[0].get_text():
                start_text = children[0].get_text().split(':')[0]
            else:
                start_text = 'Ordliste:' if ramme.find('dl') else 'Ramme:'
            if not children[-1].get_text().endswith('slutt') and len(children)>1:
                end_p = soup.new_tag('p')
                end_p.string = f'{start_text.replace(":","")} slutt'
                ramme.append(end_p)
            if children_tags:
                if not ('class' in children_tags[0] and children_tags[0]['class'] == 'blank_line'):
                    opening_blank_line = soup.new_tag('p')
                    opening_blank_line['class'] = 'blank_line'
                    ramme.insert(0, opening_blank_line)
                if not ('class' in children_tags[-1] and children_tags[-1]['class'] == 'blank_line'):
                    ending_blank_line = soup.new_tag('p')
                    ending_blank_line['class'] = 'blank_line'
                    ramme.append(ending_blank_line)
    
    # 4.17.1 Tables
    # -------------
    for table in soup.find_all('table'):
        # hopp over hvis det allerede ligger en table-summary rett foran
        prev = _prev_tag_sibling(table)
        if prev and 'class' in prev.attrs and 'table-summary' in prev.get('class', []):
            continue

        cols, rows = _count_table_dimensions(table)
        text = (
            f"Tabell, {cols} {_no_plural(cols, 'kolonne', 'kolonner')}, "
            f"{rows} {_no_plural(rows, 'rad', 'rader')}:"
        )

        #print(text)
        #print(table)

        blank_line = soup.new_tag('p')
        blank_line['class'] = 'blank_line'
        table.insert_before(blank_line)
        p = soup.new_tag('p')
        p['class'] = ['table-summary']
        p.string = text
        table.insert_before(p)
        #print(table)

    # 4.17.2 Strukturinformasjon ved lister med utgangspunkt i tabeller
    # -----------------------------------------------
    # -> manually

    # 4.18 Tilretteleggers kommentarer
    # -------------------------------
    # -> manually

    # 4.19 Statpeds produksjonsnummer
    # -------------------------------
    logger.info('4.19 Statpeds produksjonsnummer')
    if (copyright_section := BODY.find('section', {'id': 'copyright'})):
        p = soup.new_tag('p')
        p.string = f'Produksjonsnummer: {metadata["production_number"]}'
        copyright_section.insert(-1, p)

    # 5 Lister
    # ========

    # 5.1 Ordnede lister
    # ------------------
    # -> pandoc

    # 5.2 Punktlister
    # ---------------
    # -> pandoc

    # 5.3 Ordlister
    # -------------
    # -> prepare_for_docx TODO: check if relevant for other formats

    # 6 Oppgaver
    # ==========

    # 6.1 Oppsett
    # ----------
    # 6.1.1 Oppgavetegn og oppgavenummerering #28
    # -------------------------------------------
    logger.info('6.1.1 Oppgavetegn og oppgavenummerering')
    for task_section in BODY('section', attrs={'class': 'task'}):
        if (heading := task_section.find(re.compile('^h[1-6]$'))):
            heading.insert(0, NavigableString('>>> '))
    
    # 6.3 Utfyllingsoppgaver #32
    # --------------------------
    logger.info('6.3 Utfyllingsoppgaver')
    for element in BODY(attrs={'class': 'answer'}):
        if element.get_text().strip() == '---':
            element.string = TASK_FILL_BLANK

    # 6.3.1 Utfylling av enkeltbokstaver i språkbøker #33
    # ---------------------------------------------------
    for element in BODY(attrs={'class': 'answer_1'}):
        if element.get_text().strip() == '-':
            element.string = TASK_FILL_BLANK_SINGLE

    # 6.4 En annen mulighet er å krysse av eller fylle inn mellom hakeparenteser [ ] #134
    # -----------------------------------------------------------------------------------
    logger.info('6.4 En annen mulighet er å krysse av eller fylle inn mellom hakeparenteser [ ]')
    for element in BODY(attrs={'class': 'box'}):
        if element.get_text().strip == '---':
            element.string = TASK_FILL_BOX

    # 7.1 Bindestrek og tankestrek #38
    # --------------------------------

    # 7.1 Tankestrek skrives med mellomrom på begge sider, mens fra–til-strek verken har mellomrom foran eller bak #140
    # 7.1 Replikkstrek/sitatstrek skal ha mellomrom mellom tegnet og replikken/sitatet #141
    # -------------------------------------------------------------------------------------
    # TODO: minus sign does not work
    logger.info('7.1 Bindestrek og tankestrek')
    for element in BODY(string=True):
        if '–' in element.string:
            updated_text = re.sub(r'(?<!\d)\s*–\s*(?!\d)', ' – ', element)
            updated_text = re.sub(r'–(?=["«])', '– ', updated_text)  # Ensures space after `–` if followed by " or «
            element.replace_with(updated_text)

    # 7.2.1 Tusenskilletegn #39
    # -------------------------

    # 7.2.1 Tall som størrelse skrives med punktum som skilletegn fra og med firesifrede tall i barneskole, som dette: 4.300, 52.000. #142

    # 7.2.1 Tall som størrelse skrives med punktum som skilletegn fra og med femsifrede tall i ungdomsskole og videregående skole, som dette:
    # 13.200, 110.000. Tall med fire siffer skrives tett på høyere trinn, som dette: 4300. #143

    # 7.2.1 Hvis vi gjengir kode, Excel, navn/ID, skrives tallet likt som i læreboken #144
    # -------------------------------------------------------------------------------------
    logger.info('7.2.1 Tusenskilletegn')
    for element in BODY(string=True):
        if element.parent.name in ["code", "pre"]:
            continue

        modified = False

        def replacer(match):
            nonlocal modified
            formatted = format_number(match.group(), GRADE)
            if formatted:
                modified = True
                return formatted
            return match.group()

        if modified:
            updated_text = re.sub(r'\b\d{1,3}(?:[ .,]\d{3})*(?:[.,]\d+)?\b', replacer, element)
            element.replace_with(updated_text)

    # 7.3 Kolon #42
    # ------------
    # Manually

    # 7.4 Anførselstegn #43
    # ---------------------
    """
    Iterates through all text elements and converts various types of quotation marks.
    """
    logger.info('7.4 Anførselstegn')
    for element in BODY(string=True):
        if element.parent.name in ["code", "pre"] or 'asciimath' in element.parent.get('class', []):
            continue

        updated_text = convert_quotes(element)

        if updated_text != element:
            element.replace_with(updated_text)

    # 7.5 Spesialtegn
    # ---------------
    # 7.5.1 Noen matematiske tegn #44 
    # 7.5.2 Noen kjemiske uttrykk #45
    # Some are implemented by 4.15.1 and 4.15.2

    # Fractions
    """
    Iterates through all text elements and replaces fraction signs according to the MATH_SIGNS dictionary.
    """
    logger.info('7.5 Spesialtegn')
    for element in BODY(string=True):
        if element.parent.name in ["code", "pre"]:  # TODO: check if relevant 
            continue

        updated_text = MATH_SIGNS_PATTERN.sub(lambda match: MATH_SIGNS[match.group(0)], element)

        if updated_text != element:
            element.replace_with(updated_text)
    
    # Indexes
    for index in BODY(['sup', 'sub']):
        if args.mathematics and len(index.get_text()) < 1:
            index.insert(0, NavigableString('('))
            index.append(NavigableString(')'))
        index.insert(0, NavigableString(INDEXES[index.name]))
        index.unwrap()

    # 7.5.3 Spesialbokstaver i fremmedspråk #46
    # 7.5.3 Til lydskrift – fonetiske symboler – brukes den samme standarden som i 6-punkt #150
    # TODO: check if relevant
    """ 
    Extracts and validates phonetic transcriptions from `<dt>` elements.
    """
    '''
    for dt in soup.find_all("dt"):
        dt_text = dt.get_text(strip=True)  # Extract text
        
        # Extract only the phonetic part inside `[ ... ]`
        phonetic_matches = IPA_REGEX.findall(dt_text)

        for match in phonetic_matches:
            pass #print(f"✅ Found phonetic transcription: [{match}] in <dt>")
    '''

    # 7.5.4 Greske bokstaver #47
    logger.info('7.5.4 Greske bokstaver')
    for element in BODY(string=True):
        new_text = replace_greek_letters(element)
        if new_text != element:
            element.replace_with(new_text)


    # 7.7 Emojier #49
    # ---------------
    # 7.7 Det blir mange tegn, så dette innføres først på 4. trinn. #155 TODO:
    # 7.7 Hvis det er flere like emojier etter hverandre, settes antallet rett etter siste kolon, slik: :smilende ansikt:3 #154
    """
    Replaces emojis in a BeautifulSoup object with their descriptions,
    grouping consecutive identical emojis as [description][count].
    Only updates the text if it has been modified.
    """
    logger.info('7.7 Emojier')
    emoji_pattern = re.compile('|'.join(re.escape(e) for e in EMOJIS.keys()))  # Regex for finding emojis
    IGNORED_SYMBOLS = {"©", "®"} # TODO: check if relevant

    for element in BODY(string=True):
        original_text = element
        new_text = []
        last_emoji = None
        count = 0
        modified = False

        for char in element:
            if char in EMOJIS and char not in IGNORED_SYMBOLS:
                modified = True
                if char == last_emoji:
                    count += 1
                else:
                    if last_emoji is not None:
                        description = EMOJIS.get(last_emoji, last_emoji)
                        new_text.append(f"{description}{count if count > 1 else ''}")
                    last_emoji = char
                    count = 1
            else:
                if last_emoji is not None:
                    description = EMOJIS.get(last_emoji, last_emoji)
                    new_text.append(f"{description}{count if count > 1 else ''}")
                    last_emoji = None
                    count = 0
                new_text.append(char)

        if last_emoji is not None:
            description = EMOJIS.get(last_emoji, last_emoji)
            new_text.append(f"{description}{count if count > 1 else ''}")

        new_text_str = ''.join(new_text)
        if modified and new_text_str != original_text:
            element.replace_with(new_text_str)

    # TODO: Chapter 8


    # 9 Unngå sammenslåtte og delte celler og tomme rader og kolonner. #186
    # ---------------------------------------------------------------------
    logger.info('9 Unngå sammenslåtte og delte celler og tomme rader og kolonner')
    for cell in BODY(['th', 'td']):
        if 'colspan' in cell.attrs:
            colspan = int(cell['colspan'])
            del cell['colspan']

            for i in range(colspan - 1):
                new_cell        = soup.new_tag(cell.name)
                new_cell.string = cell.get_text()
                cell.insert_after(new_cell)

    rows = BODY('tr')
    for row_idx, row in enumerate(rows):
        cells = row.find_all(['td', 'th'])
        for cell_idx, cell in enumerate(cells):
            if 'rowspan' in cell.attrs:
                rowspan = int(cell['rowspan'])
                del cell['rowspan']

                for r in range(1, rowspan):
                    if row_idx + r < len(rows):
                        new_row = rows[row_idx + r]
                        new_cell = soup.new_tag(cell.name)
                        new_cell.string = cell.get_text()
                        new_row.insert(len(new_row.find_all(['td', 'th'])), new_cell)

    # 9.3 Tabell som liste #77
    # ------------------------
    # Manually

    # 9.4 Tabell som relieff-figur #78
    # --------------------------------
    # Manually

    # 10.1 Ordforklaringer #80
    # ------------------------
    logger.info('10.1 Ordforklaringer')
    dd_elements = 0
    for dd in BODY('dd'):
        dd_elements += 1
        dd['id'] = f'dd_{dd_elements}'

    for dl in BODY('dl'):
        # Step 1: Extract expressions from <dt> elements in the <dl>
        expressions = {
                dt : re.sub(r"[\(\[].*?[\)\]]", "", dt.get_text()).strip().rstrip(":").strip()
                for dt in dl.find_all("dt")
                }

        dl_section      = None
        text_section    = None
        dl_before_text  = False

        # Find text section
        for parent in dl.parents:
            if parent.name == 'section':
                dl_section = parent
                if ((previous_section := dl_section.find_previous('section')) and
                    all(expr.lower() in previous_section.get_text() for expr in expressions.values())):
                        text_section = previous_section
                        break
                elif ((next_section := dl_section.find_next('section')) and
                    all(expr.lower() in next_section.get_text() for expr in expressions.values())):
                        dl_before_text = True
                        text_section = next_section
                        break
                break

        # 10.1 Samling #260
        logger.info('10.1 Samling')
        if GRADE <= 5: # and dl_section and text_section and not dl_before_text:
            for dl in BODY('dl'):
                # TODO: dl in tables, p heading 'glossary'
                heading = None
                for parent in dl.parents:
                    if parent.name == 'aside' and (heading := parent.find(attrs={'epub:type':'bridgehead'})):
                        break
                    if parent.name == 'section' and (heading := parent.find(re.compile('^h[1-6]$'))):
                        break    
                if heading:
                    if (next_sibling := heading.find_next_sibling()) and next_sibling.name == 'dl':
                        for element in dl:
                            next_sibling.append(element)
                    else:
                        heading.insert_after(dl)

        # 10.1 De enkelte ordene skal stå fra marg, etterfulgt av kolon, mellomrom og ordforklaringen. #262 TODO
        # 10.1 De enkelte ordene skal stå fra marg, etterfulgt av kolon, mellomrom og ordforklaringen. #262 -> pandoc
        # 10.1 Fra og med 6. trinn brukes listeoppsett med hengende innrykk, uten innledende tegn. #263 -> pandoc

        # 10.1 Det kan eventuelt settes inn hyperkoblinger fra ordene i teksten til ordforklaringene #264
        logger.info('10.1 Det kan eventuelt settes inn hyperkoblinger fra ordene i teksten til ordforklaringene')
        if args.link_footnotes and text_section and dl_section:
            for dt, expression in expressions.items():
                dd = dt.find_next('dd')
                if dd and 'id' in dd.attrs:
                    dd_id = dd['id']
                    regex = re.compile(rf'\b{re.escape(expression)}\b')
                    for element in text_section.find_all(string=True):
                        if regex.search(element):
                            before, match, after = safe_split(element, regex)
                            if match:
                                new_tag = soup.new_tag('a', href=f'#{dd_id}')
                                new_tag.string = match
                                if before:
                                    element.insert_before(before)
                                element.insert_before(new_tag)
                                if after:
                                    element.insert_before(after)
                                element.extract()

    # 10.1 Gloselister behandles på samme måte som ordforklaringer, men innledes med teksten Gloser: eller
    # eventuelt det begrepet som brukes i originalboka. #261
    logger.info('10.1 Gloselister #261')
    for section in BODY('section', attrs={'class': 'glossary'}):
        if (h := section.find(re.compile('^h[1-6]$'))) and 'gloser' not in h.get_text().lower():
            if h.get_text().lower().startswith('xxx'):
                parts = h.get_text().split(' ')
                #h.string = ' '.join(parts[0] + ['Gloser:'] ' '.join(parts[1:]))
            else:
                h.string = f'Gloser: {h.get_text()}'

    # 14.4 De skal være på formen: Bokas tittel (antall sider) – Målform – Forfatter(e). #201
    # Ref. 08: Bokas tittel settes med tittelstil på første linje. På neste linje angis startside
    # og sluttside for det stoffet fra originalboka som er med i den tilrettelagte filen
    '''
    logger.info('14.4 De skal være på formen: Bokas tittel (antall sider) – Målform – Forfatter(e) #201')
    if (titlepage := BODY.find('section', attrs={'epub:type': 'frontmatter titlepage'})):
        titlepage.clear()
        h1 = soup.new_tag('h1', attrs={'epub:type': 'fulltitle'})
        h1.string = metadata['title']
        titlepage.append(h1)
        p = soup.new_tag('p')
        p.string = f'side {metadata["pagenumbers"][0]} til {metadata["pagenumbers"][-1]}'
        titlepage.append(p)
    '''
    logger.info('14.4 De skal være på formen: Bokas tittel (antall sider) – Målform – Forfatter(e) #201')

    if (titlepage := BODY.find('section', attrs={'epub:type': 'frontmatter titlepage'})):
        titlepage.clear()

        h1 = soup.new_tag('h1', attrs={'epub:type': 'fulltitle'})

        title = (metadata.get('title') or '').strip()

        pagenumbers = metadata.get('pagenumbers') or []
        page_count_text = f'({len(pagenumbers)} sider)' if pagenumbers else ''

        lang = (metadata.get('language') or '').strip().lower()
        maalform = {'nb': 'Bokmål', 'nn': 'Nynorsk'}.get(lang, '')

        authors = metadata.get('authors') or []
        if len(authors) == 1:
            author_text = (authors[0] or '').strip()
        elif len(authors) > 1:
            first = (authors[0] or '').strip()
            surname = first.split()[-1] if first else ''
            author_text = f'{surname} mfl.' if surname else 'mfl.'
        else:
            author_text = ''

        first_part = ' '.join(part for part in [title, page_count_text] if part)
        line = ' – '.join(part for part in [first_part, maalform, author_text] if part)

        h1.string = line
        titlepage.append(h1)

    # 4.5 Innholdsfortegnelse
    # To be removed in prepare_for_docx and added with pandoc
    logger.info('4.5 Innholdsfortegnelse')

    # Remove previous TOCS
    for toc in BODY(attrs={'epub:type': ['toc', 'frontmatter toc']}):
        logger.info('Table of contents found')
        toc.decompose()

    # Remove page list and landmark list
    if page_list := BODY.find('nav', attrs={'epub:type': 'page-list'}):
        logger.info('Removing page list')
        page_list.decompose()
    if landmark_list := BODY.find('nav', attrs={'epub:type': 'landmarks'}):
        logger.info('Removing landmark list')
        landmark_list.decompose()

    toc = soup.new_tag('section')
    empty_line = soup.new_tag('p')
    toc.append(empty_line)

    # TODO: check formatting
    for heading in BODY(re.compile(f'^h[1-{TOC_LEVELS}]$'), attrs={'id': True}): 
        for parent in heading.parents:
            if parent.name == 'section':
                if 'epub:type' in parent.attrs and 'backmatter' not in parent['epub:type']:
                    p = soup.new_tag('p')
                    if args.grade > 7: 
                        a = soup.new_tag('a', href=f'#{heading["id"]}')
                        a.string = heading.get_text()
                        p.append(a)
                    else:
                        p.string = heading.get_text()
                    toc.append(p)

    first_lines.insert_after(toc)

    # 4.14 Blank linje
    # ----------------
    logger.info('4.14 Blank linje')

    for toc in BODY(attrs={'epub:type': ['toc', 'frontmatter toc']}):
        p_blank = soup.new_tag('p')
        p_blank['class'] = 'blank_line'
        toc.insert_before(p_blank)
    for heading in BODY(re.compile('^h[1-6]$')):
        if ((previous_text_element := previous_text_node(heading)) and
            not is_pagenumber(previous_text_element) and
            not previous_text_element.parent.name in ['h1','h2','h3','h4','h5','h6'] and
            not 'aside' in [parent.name for parent in heading.parents]):
                p_blank = soup.new_tag('p')
                p_blank['class'] = 'blank_line'
                heading.insert_before(p_blank)
    for aside in BODY('aside'):
        if 'class' in aside.attrs.keys() and 'ramme' in aside['class']:
            pass # TODO: check if there are asides without blank lines


    # TODO: structure information, tasks, lists

    # ========================

    # Add information on conversion. This is used by bok_to_docx
    if (head := soup.head):
        meta = soup.new_tag('meta', charset='utf-8')
        meta['name'] = 'dc:conformsTo'
        meta['content'] = 'Statped_electronic_book_standard'


    return soup
'''
def convert(args, logger):
    try:
        soup = BeautifulSoup(args.data, "xml")
    except Exception:
        soup = BeautifulSoup(args.data, "lxml-xml")

    soup = apply_requirements(soup, args, logger)
    return soup.prettify(formatter="minimal").encode("utf-8")
'''

def convert(args):
    args.logger.info("Laster inn XHTML-fil: %s", args.input)
    args.logger.info(f'args: {args}')
    with open(args.input, 'r', encoding='utf-8') as file:
        try:
            soup = BeautifulSoup(file, "xml")
        except Exception:
            soup = BeautifulSoup(file, "lxml-xml")

        soup = apply_requirements(soup, args, args.logger)

        '''
        if args.job_dir.exists():
            args.logger.info("Fjerner gammel output-mappe: %s", args.job_dir)
            rmtree(args.job_dir)
        args.job_dir.mkdir(parents=True, exist_ok=True)

        final_name = f"{args.production_number}.xhtml" if args.production_number else "output.xhtml"
        with open(args.job_dir / final_name, "wb") as output_file:
            output_file.write(
                soup.prettify(formatter="minimal").encode("utf-8")
            )

        #return soup.prettify(formatter="minimal").encode("utf-8")
        return 0
        '''

        rmtree(args.job_dir, ignore_errors=True)
        makedirs(args.job_dir, exist_ok=True)
        with open(args.job_dir / f"{args.production_number}.xhtml", "wb") as f:
            f.write(soup.prettify(formatter="minimal").encode("utf-8"))
        status = "success" # ?
        message = "Fil er konvertert fra xhtml til xhtml utfra Bokstandarden."
        return {"status": status, "message": message}


def transform_xhtml_string_to_bok(
    xhtml: str,
    *,
    # Samme navn som i parseren, men med Python-id's for de med bindestrek
    output: Optional[str] = None,
    mathematics: bool = False,
    science: bool = False,
    verbose: bool = False,
    toc_levels: Optional[int] = None,
    grade: Optional[int] = None,
    p_length: Optional[int] = None,
    link_footnotes: bool = False,
    index: bool = False,
) -> str:
    """
    Wrapper rundt din apply_requirements(soup, args, logger).
    Leser XHTML (str) -> BeautifulSoup("xml") -> apply_requirements(...) -> str.
    """
    args = _build_args_namespace(
        input_value="INLINE",
        output=output,
        mathematics=mathematics,
        science=science,
        verbose=verbose,
        toc_levels=toc_levels,
        grade=grade,
        p_length=p_length,
        link_footnotes=link_footnotes,
        index=index,
    )
    logger = _make_logger(verbose=verbose)

    # Viktig med XML-parser for å bevare namespaces/prefiks (epub:..., xml:lang osv.)
    soup = BeautifulSoup(xhtml, "xml")

    result = apply_requirements(soup, args, logger)

    # apply_requirements kan returnere en soup, streng eller None (muterer soup).
    if result is None:
        return str(soup)
    if isinstance(result, BeautifulSoup):
        return str(result)
    return str(result)


def transform_xhtml_file_to_bok(
    in_path: Union[str, Path],
    *,
    output: Optional[str] = None,
    mathematics: bool = False,
    science: bool = False,
    verbose: bool = False,
    toc_levels: Optional[int] = None,
    grade: Optional[int] = None,
    p_length: Optional[int] = None,
    link_footnotes: bool = False,
    index: bool = False,
) -> str:
    """
    Wrapper som leser fra filsti og kaller transform_xhtml_string_to_bok
    med samme argumenter.
    """
    p = Path(in_path)
    xml = p.read_text(encoding="utf-8", errors="replace")
    return transform_xhtml_string_to_bok(
        xml,
        output=output,
        mathematics=mathematics,
        science=science,
        verbose=verbose,
        toc_levels=toc_levels,
        grade=grade,
        p_length=p_length,
        link_footnotes=link_footnotes,
        index=index,
    )

# MAIN
# ====

def main():
    # Parse command line arguments
    parser = ArgumentParser(description='''
        Convert an epub conforming to the Nordic Guidelines for the
        Production of Accessible EPUB 3 to an epub conforming to the
        Statped Mark-up Requirements specification.
        ''')

    parser.add_argument('input',
                        help = 'The input file')
    parser.add_argument('-o',
                        '--output',
                        help = 'The output file')
    parser.add_argument('-m',
                        '--mathematics',
                        help = 'The epub is a mathematics book',
                        action = 'store_true')
    parser.add_argument('-s',
                        '--science',
                        help = 'The epub is a sience book',
                        action = 'store_true')
    parser.add_argument(
                        '-v', '--verbose',
                        action='count',
                        default=0,
                        help='Increase verbosity: -v=INFO, -vv=DEBUG'
                        )
    parser.add_argument('-t',
                        '--toc-levels',
                        help = 'The number of levels in the table of contents',
                        type = int)
    parser.add_argument('-g',
                        '--grade',
                        help = 'The grade level of the book',
                        type = int)
    parser.add_argument('-p',
                        '--p-length',
                        help = 'The maximum length of a small paragraph',
                        type = int)
    parser.add_argument('-l',
                        '--link_footnotes',
                        help = 'Link to footnotes in the text',
                        action = 'store_true')
    parser.add_argument('-i',
                        '--index',
                        help = 'Remove indexes',
                        action = 'store_true')

    args = parser.parse_args()

    # Set up logger
    configure_logging(args.verbose)
    logger = getLogger(__name__)

    # Check if input folder exists
    if not path.exists(args.input):
        logger.error('Input file does not exist')
        return
    
    # Create soup object
    with open(path.join(args.input), 'r') as file:
        soup = BeautifulSoup(file, "xml")

    production_number = find_production_number(soup)

    # Create output folder. Remove old output folder if it exists
    if path.exists(path.join(OUTPUT_DIR, production_number)):
        logger.info('Removing old output folder')
        rmtree(path.join(OUTPUT_DIR, production_number))
    makedirs(path.join(OUTPUT_DIR, production_number))

    # Convert epub
    new_soup = apply_requirements(soup, args, logger)

    # Overwrite the xhtml file in the output folder
    # TODO: implement in app.py
    with open(path.join(OUTPUT_DIR, production_number, find_filename(soup)), "w", encoding="utf-8") as file:
        # Write the XML declaration manually
        file.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        
        # Write the DOCTYPE manually
        file.write('<!DOCTYPE html>\n')

        # Get the content of the soup without adding an extra html tag
        body_content = ''.join(str(tag) for tag in soup.html.contents)

        # Write the correct html tag, ensuring the attributes remain unchanged
        file.write('<html xmlns:xml="http://www.w3.org/XML/1998/namespace" xmlns:epub="http://www.idpf.org/2007/ops" xmlns="http://www.w3.org/1999/xhtml" epub:prefix="z3998: http://www.daisy.org/z3998/2012/vocab/structure/#" lang="nb" xml:lang="nb">')
        file.write(body_content)
        file.write('</html>')

    # Output log
    formatter       = Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler    = FileHandler('test.log')
    console_handler = StreamHandler()
    
    file_handler.setLevel(DEBUG if args.verbose else INFO)
    file_handler.setFormatter(formatter)

    console_handler.setLevel(INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    

if __name__ == '__main__':
    main()
