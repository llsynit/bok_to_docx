#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
bok_to_docx.py — én-filskonverterer for XHTML/EPUB → DOCX

Integrert pipeline (tidligere tre filer samlet i én):
  1) Forberedelse (tidl. prepareXdocx.py)
  2) Pandoc-konvertering (tidl. pandoc_wrapper.py)
  3) Rydding/etterbehandling i DOCX (tidl. clean.py)

Bruk
----
CLI:
  python bok_to_docx.py convert INPUT [-o out.docx] [--stdout]
      [--reference-docx ref.docx] [--pandoc-arg ...]
      [--grade N] [-m|--mathematics] [-s|--science] [-t|--toc-levels N]
      [--no-excel] [--log-level INFO|DEBUG|...]

Eksempler:
  # Fil → DOCX
  python bok_to_docx.py convert book.xhtml -o book.docx

  # Mappa til en utpakket EPUB → DOCX (finner hoved-.xhtml automatisk)
  python bok_to_docx.py convert unpacked_epub_dir -o out.docx

  # Stdin → stdout
  cat book.xhtml | python bok_to_docx.py convert - --stdout > out.docx

Som bibliotek:
  from bok_to_docx import xhtml_to_docx
  bytes_out = xhtml_to_docx(xhtml_bytes, "out.docx", reference_docx=Path("static/TEMPLATE_SENIOR.docx"))

Avhenger av:
  - pandoc (må finnes i PATH, eller sett PANDOC_BIN)
  - Python-pakker: beautifulsoup4, lxml, pandas, python-docx

© 2025
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional, Sequence

# --- 3.partsbibliotek (må være installert) -----------------------------------
from bs4 import BeautifulSoup, NavigableString
from pandas import DataFrame
from docx import Document
from docx.text.paragraph import Paragraph
from docx.shared import Pt
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

# --- lokale imports ---------------------------------------------------------------
#from statpub2bok import apply_requirements


# --- Konstanter / miljø -------------------------------------------------------
DEFAULT_LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
PANDOC_BIN = os.getenv("PANDOC_BIN", "pandoc")
TEMPLATE_JUNIOR = "TEMPLATE_JUNIOR.docx"
#TEMPLATE_SENIOR = "TEMPLATE_SENIOR.docx"
TEMPLATE_SENIOR = "TEMPLATE_SENIOR.dotm"

THIS_DIR = Path(__file__).resolve().parent
STATIC_DIR = THIS_DIR / "static"
OUTPUT_DIR = THIS_DIR / "artifacts"

# Marker/”tokens” brukt både i prepare og clean:
EMPTY = "blank_line"
NOINDENT = "NOINDENT"
TOINN = "TOINN"
NUMBER_PREFIX = "--- "
GLOSSARY_ENTRY_PREFIX = "STATPED_GLOSSARY_ENTRY::"
TOC_LEVEL_PREFIX = "STATPED_TOC_LEVEL::"
TOC_INDENT_STEP_PT = 18  # 0,635 cm per nivå etter nivå 1
GLOSSARY_HANGING_INDENT_PT = 18  # 360 twips / 0,635 cm

DEFAULT_GRADE = 8  # barnetrinn-regel (fontvalg mm i clean)
FONT_NAME_JUNIOR = "Courier New"
FONT_NAME_SENIOR = "Verdana"
FONT_SIZE_JUNIOR = 12
FONT_SIZE_SENIOR = 13

# Tittel-opprydding:
LANGUAGES_TRAILING = ["Bokmål", "Nynorsk", "BokmÃ¥l"]  # OBS: inkluder mulig ikke-UTF8-rest

# Excel-deteksjon
MAX_TABLE_WIDTH_CHARS = 54  # ca. bredde for å vurdere om tabell bør ut
EXCEL_DIRNAME = "Excel"

DEFAULT_PRODUCTION_NUMBER = "000"

# ------------------------------------------------------------------------------
def configure_logging(level: str = DEFAULT_LOG_LEVEL) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

logger = logging.getLogger("bok_to_docx")

def find_production_number(soup: BeautifulSoup) -> str:
    if (meta := soup.find("meta", attrs={"name": "dc:identifier"})) and meta.has_attr("content"):
        return meta["content"].strip()
    else:
        return DEFAULT_PRODUCTION_NUMBER

def get_ref_doc(args):
    if args.reference_docx is not None:
        return args.reference_docx
    elif args.grade is not None and args.grade < 8:
        return os.path.join(STATIC_DIR, TEMPLATE_JUNIOR)
    else:
        return os.path.join(STATIC_DIR, TEMPLATE_SENIOR)

# ==============================================================================
# 1) PREPARE (tidligere prepareXdocx.py — forkortet/robustifisert)
# ==============================================================================

def is_book(soup) -> bool:
    return soup.find("meta", attrs={"name": "dc:conformsTo", "content": "Statped_electronic_book_standard"}) is not None

def run_statpub_to_bok_conversions(soup, args, logger):
    return apply_requirements(soup, args, logger)

def get_table_width_chars(table) -> int:
    """Estimér ca. tegnbredde for tabellen basert på antall kolonner."""
    max_cols = 0
    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        max_cols = max(max_cols, len(cells))
    # ca. 10 tegn pr kolonne – justerbar heuristikk
    return max_cols * 10


def is_excel_like_table(table) -> bool:
    """
    En enkel gjenkjenning av “Excel-lignende” tabell:
      1) øverste venstre celle tom
      2) første rad (unntatt col 0) A, B, C …
      3) første kolonne (unntatt rad 0) 1, 2, 3 …
    """
    if not table or table.name != "table":
        return False

    rows = table.find_all("tr")
    if len(rows) < 2:
        return False

    first_row_cells = rows[0].find_all(["td", "th"])
    first_col_cells = [r.find(["td", "th"]) for r in rows[1:]]

    # (1) tom øvre-venstre?
    if first_row_cells and first_row_cells[0].get_text(strip=True):
        return False

    # (2) A, B, C...
    expected_headers = [chr(ord("A") + i) for i in range(len(first_row_cells)-1)]
    actual_headers = [c.get_text(strip=True) for c in first_row_cells[1:]]
    if actual_headers[:len(expected_headers)] != expected_headers[:len(actual_headers)]:
        return False

    # (3) 1, 2, 3...
    for i, cell in enumerate(first_col_cells, start=1):
        if not cell:
            return False
        if cell.get_text(strip=True) != str(i):
            return False

    return True

@dataclass
class PrepareArgs:
    mathematics: bool = False
    science: bool = False
    verbose: bool = False
    toc_levels: Optional[int] = None
    grade: Optional[int] = None
    no_excel: bool = False

def _prepend_blank_line(soup, element):
    """Sett inn en EMPTY_LINE før 'element' når hensiktsmessig."""
    empty_p = soup.new_tag("p")
    empty_p.string = EMPTY
    element.insert_before(empty_p)


def _normalize_inline_text(element) -> str:
    """Hent lesbar tekst med ett mellomrom mellom tekstfragmentene."""
    return " ".join(element.get_text(" ", strip=True).split())


def _definition_list_groups(dl):
    """
    Del en HTML-definisjonsliste i grupper av én/flere termer og forklaringer.

    HTML tillater både flere dt før samme dd og flere dd etter samme dt. Hver
    gruppe returneres derfor som (terms, definitions), slik at vi ikke mister
    innhold når kildedataene bruker en av disse variantene.
    """
    items = dl.find_all(["dt", "dd"], recursive=False)
    if not items:
        # Tåler et unødvendig wrapper-element rundt dt/dd.
        items = dl.find_all(["dt", "dd"])

    groups = []
    terms = []
    definitions = []

    def flush():
        nonlocal terms, definitions
        if terms or definitions:
            groups.append((terms, definitions))
        terms = []
        definitions = []

    for item in items:
        text = _normalize_inline_text(item)
        if not text:
            continue

        if item.name == "dt":
            if definitions:
                flush()
            terms.append(text)
        else:
            definitions.append(text)

    flush()
    return groups


def _ensure_definition_list_aside_markers(soup: BeautifulSoup) -> None:
    """
    Sørg for faste ordlistemarkører rundt en dl som ligger i en aside.

    Funksjonen håndterer både rå XHTML uten markører og XHTML som allerede er
    behandlet av en eldre statpub_to_bok-versjon. Den eldre versjonen kunne
    bruke teksten før det første kolonet i en dd som rammenavn.
    """
    for aside in soup.find_all("aside"):
        if aside.find("dl") is None:
            continue

        direct_children = [
            child
            for child in aside.children
            if getattr(child, "name", None) is not None
        ]

        def is_blank_line(element) -> bool:
            classes = element.get("class", [])
            return (
                "blank_line" in classes
                or not element.get_text(" ", strip=True)
            )

        content_children = [
            child for child in direct_children if not is_blank_line(child)
        ]
        if not content_children:
            continue

        first = content_children[0]
        last = content_children[-1]
        first_text = _normalize_inline_text(first).casefold()
        last_text = _normalize_inline_text(last).casefold()

        # Har statpub_to_bok allerede satt inn en sluttmarkør, er første
        # innholdselement den tilhørende startmarkøren – også når teksten der
        # ble feilaktig hentet fra dl-innholdet.
        previously_framed = (
            last.name == "p" and last_text.endswith("slutt")
        )

        if previously_framed and first.name == "p":
            first.clear()
            first.string = "Ordliste:"
        elif first.name == "p" and first_text.startswith("ordliste:"):
            first.clear()
            first.string = "Ordliste:"
        else:
            opening = soup.new_tag("p")
            opening.string = "Ordliste:"
            first.insert_before(opening)

        if previously_framed:
            last.clear()
            last.string = "Ordliste slutt"
        else:
            closing = soup.new_tag("p")
            closing.string = "Ordliste slutt"
            # Sett sluttmarkøren før en eventuell avsluttende blank_line.
            content_children[-1].insert_after(closing)


def _convert_definition_lists_to_glossary_paragraphs(soup: BeautifulSoup) -> None:
    """
    Gjør dl/dt/dd om til vanlige avsnitt før Pandoc.

    Et internt prefiks følger hvert oppslagsavsnitt gjennom Pandoc. Prefikset
    fjernes i DOCX-etterbehandlingen og brukes til å skille selve oppslagene
    fra for eksempel sidetall og innledningen «Ordforklaringer:».
    """
    for dl in list(soup.find_all("dl")):
        replacement_paragraphs = []

        for terms, definitions in _definition_list_groups(dl):
            definition = "; ".join(definitions).strip()

            if terms:
                for term in terms:
                    term = term.rstrip().rstrip(":").rstrip()
                    text = f"{term}: {definition}" if definition else f"{term}:"
                    paragraph = soup.new_tag("p")
                    paragraph.string = f"{GLOSSARY_ENTRY_PREFIX}{text}"
                    replacement_paragraphs.append(paragraph)
            elif definition:
                paragraph = soup.new_tag("p")
                paragraph.string = f"{GLOSSARY_ENTRY_PREFIX}{definition}"
                replacement_paragraphs.append(paragraph)

        for paragraph in replacement_paragraphs:
            dl.insert_before(paragraph)
        dl.decompose()




def _split_explicit_exercise_parts_into_paragraphs(soup: BeautifulSoup) -> None:
    """
    Splitt oppgaveavsnitt som allerede har semantiske markører til egne <p>.

    Eksempel:
      <p><span class="exercisenumber">>>> 1.</span><br/> Intro
         <span class="excercisepart">a.</span> ...
         <span class="excercisepart">b.</span> ...</p>

    blir til ett avsnitt for oppgavenummeret, ett for innledningen og ett for
    hver underoppgave. Inline-markup i hvert segment beholdes. Vi støtter både
    den etablerte (feilstavede) klassen ``excercisepart`` og ``exercisepart``.
    """
    part_classes = {"excercisepart", "exercisepart"}

    def is_part_marker(node) -> bool:
        if getattr(node, "name", None) != "span":
            return False
        classes = set(node.get("class", []))
        return bool(classes & part_classes)

    def is_number_marker(node) -> bool:
        return (
            getattr(node, "name", None) == "span"
            and "exercisenumber" in set(node.get("class", []))
        )

    def segment_has_content(nodes) -> bool:
        for node in nodes:
            if isinstance(node, NavigableString):
                if str(node).strip():
                    return True
            elif getattr(node, "name", None) == "br":
                continue
            elif getattr(node, "get_text", None):
                if node.get_text(" ", strip=True):
                    return True
        return False

    def trim_segment(nodes):
        nodes = list(nodes)
        while nodes:
            first = nodes[0]
            if getattr(first, "name", None) == "br":
                nodes.pop(0)
                continue
            if isinstance(first, NavigableString) and not str(first).strip():
                nodes.pop(0)
                continue
            break
        while nodes:
            last = nodes[-1]
            if getattr(last, "name", None) == "br":
                nodes.pop()
                continue
            if isinstance(last, NavigableString) and not str(last).strip():
                nodes.pop()
                continue
            break
        return nodes

    # list(...) fordi DOM-en muteres underveis.
    for paragraph in list(soup.find_all("p")):
        children = list(paragraph.contents)
        if not any(is_number_marker(n) for n in children):
            continue

        # Vi splitter bare når oppgavenummeret faktisk er et direkte barn av p.
        # Dermed unngår vi å rive fra hverandre mer komplisert nested markup.
        number_index = next((i for i, n in enumerate(children) if is_number_marker(n)), None)
        if number_index is None:
            continue

        segments = []
        current = []
        kind = "prefix"

        for node in children:
            if is_number_marker(node):
                if segment_has_content(current):
                    segments.append((kind, trim_segment(current)))
                current = [node]
                kind = "number"
                continue

            if is_part_marker(node):
                if segment_has_content(current):
                    segments.append((kind, trim_segment(current)))
                current = [node]
                kind = "part"
                continue

            # <br> rett etter oppgavenummeret er bare separator og skal ikke
            # bli med inn i neste avsnitt.
            if kind == "number" and getattr(node, "name", None) == "br":
                if segment_has_content(current):
                    segments.append((kind, trim_segment(current)))
                current = []
                kind = "intro"
                continue

            current.append(node)

        if segment_has_content(current):
            segments.append((kind, trim_segment(current)))

        # Ingen faktisk splitting nødvendig.
        if len(segments) <= 1:
            continue

        for _kind, nodes in segments:
            if not segment_has_content(nodes):
                continue
            new_p = soup.new_tag("p")
            # Behold relevante attributter på originalavsnittet (lang, dir osv.).
            for key, value in paragraph.attrs.items():
                new_p.attrs[key] = value
            for node in nodes:
                new_p.append(node.extract() if getattr(node, "parent", None) is not None else node)
            paragraph.insert_before(new_p)

        paragraph.decompose()


def prepare_soup(soup: BeautifulSoup, args: ArgumentParser) -> BeautifulSoup:
    print(args)
    """
    Forbered HTML/XHTML for Pandoc/DOCX:
      - pagebreak → ‘--- N’ avsnitt
      - blank linje (EMPTY_LINE) foran overskrifter (m.fl.)
      - enkel regel for figurer/bilder → 'Bilde: alt-tekst'
      - listejustering / innrykk med TOINN
      - "Excel-lignende" tabeller flyttes ut til CSV (hvis ikke --no-excel)
    """
    #grade = args.grade if args.grade is not None else DEFAULT_GRADE

    if args.book or not is_book(soup):
        logger.info(f'Applying conversions from statpub_to_bok for {args.book}')
        #soup = run_statpub_to_bok_conversions(soup, args, logger)

    if args.grade and isinstance(args.grade, int):
        args.grade = int(args.grade)
    else:
        for keyword in soup('meta', attrs={'name':'dc:subject.keyword'}):
            if 'content' in keyword.attrs and keyword['content'].isdigit():
                args.grade = int(keyword['content'])
                break
    if not args.grade:
        args.grade = 10  # default høyeste nivå

    logger.info(f'Assumed grade level: {args.grade}')

    # En aside med dl skal alltid ha de faste markørene «Ordliste:» og
    # «Ordliste slutt», også dersom en eldre statpub_to_bok allerede har satt
    # inn feil markørtekst.
    _ensure_definition_list_aside_markers(soup)

    # Pandoc gir dl/dt/dd sitt eget definisjonslisteoppsett. Gjør derfor hvert
    # oppslag om til ett vanlig, merket avsnitt før konverteringen. Den endelige
    # marg-/hengende-formateringen settes i DOCX etter Pandoc.
    _convert_definition_lists_to_glossary_paragraphs(soup)

    # Oppgaver kan være pakket i ett XHTML-avsnitt. Splitt eksplisitt merkede
    # oppgavenummer/underoppgaver før Pandoc, slik at hvert punkt blir et ekte
    # DOCX-avsnitt og kan starte fra margen.
    _split_explicit_exercise_parts_into_paragraphs(soup)

    # Remove pagebreak tags
    for pagebreak in soup(attrs={'epub:type':'pagebreak'}):
        pagebreak.decompose()

    if args.production_number == DEFAULT_PRODUCTION_NUMBER:
        args.production_number = find_production_number(soup)
        args.logger.warning("Produksjonsnummer ikke funnet i metadata, bruker fallback: %s", args.production_number)



    # Excel-lignende tabeller: trekk dem ut (om ikke slått av)
    if not args.no_excel:
        args.logger.info("Tabeller: Excel-sjekk og mulig utskilling")
        excel_root = OUTPUT_DIR / EXCEL_DIRNAME
        if excel_root.exists():
            shutil.rmtree(excel_root)
        excel_root.mkdir(parents=True, exist_ok=True)

        tables_to_extract = []
        for t in soup.find_all("table"):
            width_chars = get_table_width_chars(t)
            if is_excel_like_table(t) or width_chars > MAX_TABLE_WIDTH_CHARS:
                tables_to_extract.append(t)

        # erstatt tabellene og lagre CSV-er
        for idx, t in enumerate(tables_to_extract, start=1):
            rows = []
            for row in t.find_all("tr"):
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                rows.append(cells)
            df = DataFrame(rows)
            csv_path = excel_root / f"table_{idx}.csv"
            df.to_csv(csv_path, index=False, header=False)

            repl = soup.new_tag("p")
            repl.string = f"[Tabell flyttet til {EXCEL_DIRNAME}/table_{idx}.csv]"
            t.insert_before(repl)
            t.decompose()

    # Innholdsfortegnelse:
    # Behold hierarkiet, men gjør listepunktene til vanlige avsnitt slik at
    # Pandoc ikke lager irrelevante Word-listenumre. Hvert avsnitt merkes med
    # TOC-nivå; nivå 1 skal fra marg, nivå 2 ett innrykk, nivå 3 to innrykk osv.
    #
    # Vi går bare gjennom direkte <li>-barn på hvert nivå. Dermed blir nivået
    # bestemt av den faktiske nesting-en i XHTML-en, ikke av tekstinnholdet.
    def _flatten_toc_list(list_tag, replacement, level=1):
        for li in list_tag.find_all("li", recursive=False):
            p = soup.new_tag("p")
            p.append(NavigableString(f"{TOC_LEVEL_PREFIX}{level}::"))

            # Eget inline-innhold i dette <li>-elementet. Underlister og
            # selvstendige blokkavsnitt behandles separat nedenfor.
            for child in list(li.contents):
                name = getattr(child, "name", None)
                if name in ("ol", "ul", "p", "div"):
                    continue
                try:
                    p.append(child.__copy__())
                except Exception:
                    p.append(NavigableString(str(child)))

            # Ikke opprett et tomt TOC-avsnitt dersom <li> bare er wrapper
            # rundt en underliste.
            own_text = p.get_text(" ", strip=True)
            marker_only = f"{TOC_LEVEL_PREFIX}{level}::"
            if own_text != marker_only:
                replacement.append(p)

            # Behold eventuelle direkte blokkavsnitt i riktig rekkefølge.
            # Dette gjelder bl.a. blank_line og "--- N" som kan ligge inne i
            # et <li>. De skal ikke arve TOC-innrykket.
            for child in list(li.children):
                if getattr(child, "name", None) == "p":
                    replacement.append(child.__copy__())

                elif getattr(child, "name", None) in ("ol", "ul"):
                    _flatten_toc_list(child, replacement, level + 1)

    for toc in list(soup.find_all(attrs={"epub:type": "toc"})):
        replacement = soup.new_tag("div")
        replacement["epub:type"] = "toc"

        # Vanligvis er selve TOC-elementet en <ol>, men håndter også en
        # section/div som inneholder en eller flere topplister.
        if toc.name in ("ol", "ul"):
            _flatten_toc_list(toc, replacement, level=1)
        else:
            for top_list in toc.find_all(["ol", "ul"], recursive=False):
                _flatten_toc_list(top_list, replacement, level=1)

        toc.replace_with(replacement)

    # Quick fixes
    for blank_line in soup(attrs={'class':EMPTY}):
        blank_line.string = EMPTY

    # Issues for grade < 8
    # <ul>
    if args.grade and args.grade < 8:

        '''
        def _li_own_text(li):
            """Tekst i <li> uten å ta med nested <ul>/<ol>."""
            parts = []
            for child in li.contents:
                if getattr(child, "name", None) in ("ul", "ol"):
                    continue
                if hasattr(child, "get_text"):
                    txt = child.get_text(" ", strip=True)
                else:
                    txt = str(child).strip()
                if txt:
                    parts.append(txt)
            return " ".join(parts).strip()
        '''

        def _li_own_blocks(li):
            """
            Returnerer direkte innhold i <li> i faktisk rekkefølge.

            Blokktyper:
              ("text", "...")          vanlig tekst
              ("blank", "")            blank_line
              ("image", "Bilde: ...")  bilde
              ("explanation", "...")   forklaring/prodnote
              ("list", <ul/ol>)        underliste

            Viktig:
            - Håndterer både <figure> og <div class="figure">.
            - Legger blank linje før og etter bilder i lister.
            - Flater ikke ut bildeblokker med get_text().
            """
            blocks = []

            def norm(text):
                return " ".join((text or "").split()).strip()

            def add_blank():
                if not blocks or blocks[-1][0] != "blank":
                    blocks.append(("blank", ""))

            def add_text(text):
                text = norm(text)
                if not text:
                    return

                if text == EMPTY:
                    add_blank()
                else:
                    blocks.append(("text", text))

            def is_generic_alt(text):
                return norm(text).lower() in {
                    "tegning",
                    "bilde",
                    "illustrasjon",
                    "foto",
                    "figur",
                    "drawing",
                    "image",
                    "illustration",
                    "photo",
                    "figure",
                }

            def handle_original_figure(fig):
                """
                Håndterer opprinnelig <figure> fra XHTML:
                  <figure>
                    <img alt="..."/>
                    <aside class="prodnote">...</aside>
                  </figure>
                """
                add_blank()

                img = fig.find("img")
                aside = fig.find("aside", class_="prodnote")

                alt = norm(img.get("alt", "")) if img else ""
                explanation = norm(aside.get_text(" ", strip=True)) if aside else ""

                if alt and not is_generic_alt(alt):
                    blocks.append(("image", f"Bilde: {alt}"))
                else:
                    blocks.append(("image", "Bilde:"))

                if explanation:
                    blocks.append(("explanation", f"Forklaring: {explanation}"))

                add_blank()

            def handle_converted_figure(fig):
                """
                Håndterer statpub_to_bok-format:
                  <div class="figure">
                    <p>Bilde:</p>
                    <p>Forklaring: ...</p>
                  </div>
                """
                add_blank()

                for p in fig.find_all("p", recursive=False):
                    txt = norm(p.get_text(" ", strip=True))

                    if not txt:
                        continue

                    if txt == EMPTY or EMPTY in p.get("class", []):
                        add_blank()
                        continue

                    if txt.startswith("Bilde:"):
                        blocks.append(("image", txt))
                        continue

                    if txt.startswith("Forklaring:"):
                        blocks.append(("explanation", txt))
                        continue

                    blocks.append(("text", txt))

                add_blank()

            for child in li.contents:
                name = getattr(child, "name", None)

                if isinstance(child, NavigableString):
                    add_text(str(child))
                    continue

                if name in ("ul", "ol"):
                    blocks.append(("list", child))
                    continue

                if hasattr(child, "get") and EMPTY in child.get("class", []):
                    add_blank()
                    continue

                if name == "p":
                    add_text(child.get_text(" ", strip=True))
                    continue

                if name == "figure":
                    handle_original_figure(child)
                    continue

                if name == "div" and "figure" in child.get("class", []):
                    handle_converted_figure(child)
                    continue

                if name == "img":
                    add_blank()
                    alt = norm(child.get("alt", ""))
                    if alt and not is_generic_alt(alt):
                        blocks.append(("image", f"Bilde: {alt}"))
                    else:
                        blocks.append(("image", "Bilde:"))
                    add_blank()
                    continue

                if name == "aside":
                    txt = norm(child.get_text(" ", strip=True))
                    if txt:
                        blocks.append(("explanation", f"Forklaring: {txt}"))
                    continue

                # Fallback, men ikke for elementer som inneholder figure/div.figure.
                # Da må vi ikke flate ut bildeinnhold.
                if hasattr(child, "find") and (
                    child.find("figure") or child.find("div", class_="figure")
                ):
                    for sub in child.contents:
                        sub_name = getattr(sub, "name", None)

                        if isinstance(sub, NavigableString):
                            add_text(str(sub))
                        elif sub_name == "figure":
                            handle_original_figure(sub)
                        elif sub_name == "div" and "figure" in sub.get("class", []):
                            handle_converted_figure(sub)
                        elif sub_name == "p":
                            add_text(sub.get_text(" ", strip=True))
                        elif sub_name in ("ul", "ol"):
                            blocks.append(("list", sub))
                    continue

                if hasattr(child, "get_text"):
                    add_text(child.get_text(" ", strip=True))

            return blocks



        def _render_list(list_tag, depth=0):
            """
            Returnerer en <div> med <p>-linjer for hele lista rekursivt.

            Barnetrinnsformat:
                -- punkt
                -- punkt
                  -- underpunkt
                    -- under-underpunkt
                -- punkt

                Bilde: ...
                Forklaring: ...

                -- enda et punkt
            """
            new_div = soup.new_tag("div")

            is_ordered = list_tag.name == "ol"

            # Behold original type ("A"/"a"), men lag også en normalisert kopi.
            type_attr = list_tag.get("type") if is_ordered else None
            type_lower = (type_attr or "").lower()

            idx_counter = 0

            for li in list_tag.find_all("li", recursive=False):
                own_blocks = _li_own_blocks(li)
                nested_lists = [
                    c for c in li.contents
                    if getattr(c, "name", None) in ("ul", "ol")
                ]

                has_own_content = bool(own_blocks)

                # Tom wrapper-li med bare underliste:
                # behold/promoter nivået slik at strukturen ikke får kunstig ekstra innrykk.
                if not has_own_content and nested_lists:
                    for nl in nested_lists:
                        child_div = _render_list(nl, depth=depth)
                        for p in child_div.find_all("p", recursive=False):
                            new_div.append(p)
                    continue

                indent = TOINN * max(depth, 0)

                if is_ordered:
                    idx_counter += 1

                    if type_lower == "a":
                        letter = chr(ord("a") + idx_counter - 1)
                        if type_attr == "A":
                            letter = letter.upper()
                        marker = f"{letter})"
                    else:
                        marker = f"{idx_counter}."

                    first_prefix = f"{indent}{marker} "
                else:
                    first_prefix = f"{indent}-- "

                continuation_prefix = indent
                first_text_written = False

                for kind, value in own_blocks:
                    p = soup.new_tag("p")

                    if kind == "blank":
                        p.string = EMPTY
                        new_div.append(p)
                        continue

                    if kind == "text":
                        if not first_text_written:
                            p.string = f"{first_prefix}{value}"
                            first_text_written = True
                        else:
                            # Flere avsnitt inne i samme <li> skal ikke få nytt listemerke.
                            p.string = f"{continuation_prefix}{value}"
                        new_div.append(p)
                        continue

                    if kind in ("image", "explanation"):
                        # Bilde/forklaring skal være ren tekst, ikke listepunkt.
                        p.string = f"{continuation_prefix}{value}"
                        new_div.append(p)
                        continue

                # Underlister skal ett nivå inn når parent-li hadde eget innhold.
                child_depth = depth + (1 if has_own_content else 0)

                for nl in nested_lists:
                    child_div = _render_list(nl, depth=child_depth)
                    for p in child_div.find_all("p", recursive=False):
                        new_div.append(p)

            return new_div

        def _is_detached(tag):
            """True hvis tag ikke lenger er en del av DOM-treet."""
            # Detached: ingen parent og ingen ancestor.
            return tag.parent is None and tag.find_parent() is None

        # Konverter bare "ytterste" lister; rekursjonen tar resten.
        # Bruk while-loop for å unngå stale references når vi muterer DOM.
        while True:
            top = None
            for cand in soup.find_all(["ul", "ol"]):
                if cand.find_parent(["ul", "ol"]):
                    continue  # nested, håndteres av rekursjonen
                if _is_detached(cand):
                    continue  # stale/detached, ignorer
                top = cand
                break

            if not top:
                break

            new_div = _render_list(top, depth=0)

            # Sett inn på en måte som tåler alle tilfeller
            if top.parent:
                top.insert_before(new_div)
                top.decompose()
            else:
                # Top-level uten parent (fragment). Erstatt ved å trekke ut og legge inn div.
                # (replace_with kan feile hvis elementet er i ferd med å være frakoblet)
                try:
                    top.extract()
                except Exception:
                    pass
                soup.append(new_div)
                try:
                    top.decompose()
                except Exception:
                    pass

        # <em> and <strong> in excercises
        for span in soup.select('.exercisenumber'):
            # Hent all tekst inni elementet
            raw = span.get_text()
            # Fjern understreker og trim whitespace/linjeskift
            cleaned = raw.replace('_', '').strip()

            # Tøm innholdet og sett ren tekst
            span.clear()
            if cleaned:
                span.append(NavigableString(cleaned))

    # Remove line breaks in headings indended for PEF
    for element in soup(attrs={'class':'braille-heading-break'}):
        element.decompose()
        # FIXME: merge text nodes?

    # Returnér et renset BeautifulSoup-objekt (som XML/XHTML)
    return BeautifulSoup(str(soup), "lxml-xml")

# ==============================================================================
# 2) PANDOC (tidligere pandoc_wrapper.py)
# ==============================================================================

@dataclass
class PandocOptions:
    pandoc_bin: str = PANDOC_BIN
    reference_docx: Optional[Path] = None
    extra_flags: Sequence[str] = ()


def run_pandoc(args, input_path: Path, output_path: Path, opts: PandocOptions) -> None:
    """
    Kjører pandoc for å lage DOCX av XHTML/HTML.
    Søker default etter static/TEMPLATE_SENIOR.docx hvis ikke eksplisitt oppgitt.
    """
    ref_doc = get_ref_doc(args)
    if ref_doc is None:
        if args.grade and args.grade <= 7:
            candidate = STATIC_DIR / TEMPLATE_JUNIOR
        else:
            candidate = STATIC_DIR / TEMPLATE_SENIOR
        if candidate.exists():
            ref_doc = candidate

    cmd = [
        opts.pandoc_bin,
        str(input_path),
        "-f", "html",
        "-t", "docx",
        "-o", str(output_path),
        "--reference-doc", str(ref_doc),
        "--standalone",
    ]
    '''
    if ref_doc and ref_doc.exists():
        cmd.extend(["--reference-doc", str(ref_doc)])
    '''

    # bruker-flagg til slutt (f.eks --strip-comments, --toc)
    if opts.extra_flags:
        cmd.extend(list(opts.extra_flags))

    args.logger.info("Kjører pandoc: %s", " ".join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except FileNotFoundError as e:
        raise RuntimeError(f"Finner ikke pandoc-binæren {opts.pandoc_bin!r}. Sett PANDOC_BIN eller legg i PATH.") from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Pandoc feilet med exit {e.returncode}") from e


# ==============================================================================
# 3) CLEAN (tidligere clean.py — kondensert, men dekker hovedregler)
# ==============================================================================

def _insert_paragraph_after(paragraph: Paragraph, text: str = "") -> Paragraph:
    new_p = OxmlElement("w:p")
    paragraph._p.addnext(new_p)
    new_para = Paragraph(new_p, paragraph._parent)
    if text:
        new_para.text = text
    return new_para


def _get_previous_paragraph(paragraph: Paragraph) -> Optional[Paragraph]:
    prev = paragraph._p.getprevious()
    while prev is not None:
        if prev.tag.endswith("}p"):
            return Paragraph(prev, paragraph._parent)
        prev = prev.getprevious()
    return None


def _is_heading_paragraph(paragraph: Optional[Paragraph]) -> bool:
    """Gjenkjenn overskrifter uavhengig av språk og store/små bokstaver."""
    if paragraph is None or paragraph.style is None:
        return False

    style_name = (paragraph.style.name or "").casefold().replace(" ", "")
    style_id = (paragraph.style.style_id or "").casefold().replace(" ", "")

    return (
        style_name.startswith("heading")
        or style_name.startswith("overskrift")
        or style_id.startswith("heading")
        or style_id.startswith("overskrift")
    )


def _is_effectively_empty(paragraph: Paragraph) -> bool:
    """True for tomme avsnitt, også med NBSP, zero-width-tegn eller blank_line."""
    text = paragraph.text or ""
    if text.strip() == EMPTY:
        return True

    text = re.sub(
        r"[\s\u00a0\u1680\u2000-\u200d\u202f\u205f\u2060\u3000\ufeff]+",
        "",
        text,
    )
    return not text


def _adjacent_content_paragraph(
    document: Document,
    paragraph_element,
    direction: int,
) -> Optional[Paragraph]:
    """
    Finn nærmeste ikke-tomme avsnitt før/etter et XML-avsnitt.

    Tabeller er en reell innholdsgrense og skal ikke hoppes over. Andre tomme
    avsnitt hoppes over, slik at også flere blanklinjer mellom to overskrifter
    blir funnet.
    """
    element = (
        paragraph_element.getprevious()
        if direction < 0
        else paragraph_element.getnext()
    )

    while element is not None:
        if element.tag == qn("w:tbl"):
            return None

        if element.tag == qn("w:p"):
            paragraph = Paragraph(element, document._body)
            if not _is_effectively_empty(paragraph):
                return paragraph

        element = element.getprevious() if direction < 0 else element.getnext()

    return None


def _remove_blank_paragraphs_between_headings(document: Document) -> None:
    """Fjern alle tomme avsnitt der nærmeste innhold på begge sider er overskrift."""
    body = document._element.body
    remove_elements = []

    for element in list(body):
        if element.tag != qn("w:p"):
            continue

        paragraph = Paragraph(element, document._body)
        if not _is_effectively_empty(paragraph):
            continue

        previous_paragraph = _adjacent_content_paragraph(
            document,
            element,
            -1,
        )
        next_paragraph = _adjacent_content_paragraph(
            document,
            element,
            1,
        )

        if (
            _is_heading_paragraph(previous_paragraph)
            and _is_heading_paragraph(next_paragraph)
        ):
            remove_elements.append(element)

    for element in remove_elements:
        if element.getparent() is body:
            body.remove(element)


def _remove_paragraph(paragraph: Paragraph) -> None:
    p = paragraph._element
    p.getparent().remove(p)
    paragraph._element = None


@dataclass
class CleanArgs:
    grade: Optional[int] = None


def format_about_book_from_margin(document: Document) -> Document:
    """All paragraphs under the final «Om boka» heading start at the margin.

    Stop at the next heading («Opphavsrett»), so copyright prose retains
    its own formatting. This also normalizes any list numbering indentation.
    """
    inside = False
    for paragraph in document.paragraphs:
        value = ' '.join((paragraph.text or '').split()).casefold().rstrip('.:')
        if value == 'om boka':
            inside = True
        elif inside and value == 'opphavsrett':
            break
        if inside:
            _set_paragraph_from_margin(paragraph, document, use_normal_no_indent=False)
            # List numbering in Word can override paragraph indentation.
            ppr = paragraph._p.pPr
            if ppr is not None and ppr.numPr is not None:
                ppr.remove(ppr.numPr)
    return document


def remove_duplicate_opening_title(document: Document) -> Document:
    """Remove only an adjacent duplicate of the document's opening title.

    Pandoc can emit the XHTML head/title as a Word Title paragraph in
    addition to the explicit first body paragraph generated upstream.
    Preserve the Title-styled paragraph and the following page-range line.
    """
    paragraphs = document.paragraphs
    if len(paragraphs) < 2:
        return document
    first, second = paragraphs[0], paragraphs[1]
    def normalize(value: str) -> str:
        return " ".join(value.split()).casefold()
    if (first.style is not None
            and first.style.name.casefold() == "title"
            and normalize(first.text)
            and normalize(first.text) == normalize(second.text)
            and second.style is not None
            and second.style.name.casefold() != "title"):
        second._element.getparent().remove(second._element)
        logger.info("Removed duplicate opening title paragraph inserted alongside Pandoc title")
    return document


def clean_document(document: Document, args: CleanArgs) -> Document:
    """
    Rydder i DOCX-innholdet:
      - EMPTY_LINE → blank avsnitt (men unngå doble)
      - TOINN → 2 mellomrom
      - NOINDENT fjernes først i linje
      - blank linje foran overskrifter hvis nødvendig
      - fjern tomme avsnitt etter tallinje '--- N'
    + enkel fontpolicy basert på trinn
    """
    grade = args.grade if args.grade is not None else DEFAULT_GRADE
    font_name = FONT_NAME_JUNIOR if grade <= 7 else FONT_NAME_SENIOR
    font_size = FONT_SIZE_JUNIOR if grade <= 7 else FONT_SIZE_SENIOR

    args.logger.info("Rydder DOCX …")

    for i, p in enumerate(list(document.paragraphs)):
        text = p.text or ""

        # Tokens
        if text.strip() == EMPTY:
            if (prev := _get_previous_paragraph(p)):
                if (
                    not prev.text.strip()
                    or prev.text.startswith(NUMBER_PREFIX)
                    or _is_heading_paragraph(prev)
                ):
                    _remove_paragraph(p)
                    continue
            p.text = " "
            text = p.text

        if TOINN in text:
            p.text = text.replace(TOINN, "  ")
            text = p.text

        if text.startswith(NOINDENT):
            p.text = text.replace(NOINDENT, "", 1)
            text = p.text

        # Unngå dobbel blank etter ‘--- N’
        if text.strip() == "":
            prev = _get_previous_paragraph(p)
            if prev and (prev.text.strip() == "" or prev.text.strip().startswith(NUMBER_PREFIX)):
                _remove_paragraph(p)
                continue

        # Blank linje før overskrifter (hvis ikke blank/side nr. fra før)
        if _is_heading_paragraph(p):
            prev = _get_previous_paragraph(p)
            if prev and not (
                not prev.text.strip()
                or prev.text.strip().startswith(NUMBER_PREFIX)
                or _is_heading_paragraph(prev)
            ):
                _insert_paragraph_after(prev, "")

    for i, p in enumerate(list(document.paragraphs)):
        if not p.text.strip() and (prev := _get_previous_paragraph(p)) and prev.text.startswith(NUMBER_PREFIX):
            _remove_paragraph(p)

    # Pandoc eller tidligere konverteringsledd kan allerede ha laget én eller
    # flere tomme w:p mellom overskriftene. Fjern dem uavhengig av opphav.
    _remove_blank_paragraphs_between_headings(document)

    # Global regel: første innholdsavsnitt etter en tom linje skal starte
    # helt fra margen, uavhengig av hvilken stil Pandoc har gitt avsnittet.
    _set_content_after_blank_lines_from_margin(document)

    # TOC-hierarkiet skal overstyre den generelle "etter blanklinje fra marg"-
    # regelen: nivå 1 fra marg, deretter ett rekursivt innrykk per nivå.
    _format_toc_indentation(document)

    return document




def _format_toc_indentation(document: Document) -> None:
    """
    Bruk XHTML-hierarkiet til å formatere innholdsfortegnelsen rekursivt.

      nivå 1: 0 pt fra marg
      nivå 2: 18 pt
      nivå 3: 36 pt
      nivå 4: 54 pt
      ...

    Markøren fjernes direkte fra Word-XML-en slik at eventuelle hyperlinks og
    annen inline-formatering i TOC-linjen bevares.
    """
    marker_re = re.compile(
        rf"^{re.escape(TOC_LEVEL_PREFIX)}(\d+)::"
    )

    for paragraph in document.paragraphs:
        full_text = paragraph.text or ""
        match = marker_re.match(full_text)
        if not match:
            continue

        level = max(1, int(match.group(1)))
        marker = match.group(0)

        # Fjern markøren uten å erstatte hele paragraph.text; det ville kunne
        # ødelegge hyperlinks og run-formattering.
        remaining = marker
        for text_node in paragraph._p.iter(qn("w:t")):
            if not remaining:
                break
            node_text = text_node.text or ""
            if not node_text:
                continue

            if remaining.startswith(node_text):
                remaining = remaining[len(node_text):]
                text_node.text = ""
            elif node_text.startswith(remaining):
                text_node.text = node_text[len(remaining):]
                remaining = ""
            else:
                # Normaltilfellet: hele markøren ligger i første w:t.
                if marker in node_text:
                    text_node.text = node_text.replace(marker, "", 1)
                    remaining = ""
                break

        indent_pt = (level - 1) * TOC_INDENT_STEP_PT
        paragraph.paragraph_format.left_indent = Pt(indent_pt)
        paragraph.paragraph_format.first_line_indent = Pt(0)
        paragraph.paragraph_format.right_indent = Pt(0)


def _set_content_after_blank_lines_from_margin(document: Document) -> None:
    """
    Sett første innholdsavsnitt etter en reell tom linje helt fra margen.

    Dette gjøres i DOCX-leddet, etter at blank_line-tokenene er normalisert,
    fordi regelen gjelder den visuelle avsnittsstrukturen i sluttresultatet
    uavhengig av hvordan XHTML-kilden var merket opp.

    Bare det første ikke-tomme avsnittet etter den tomme linjen berøres.
    Flere tomme linjer på rad behandles som én avstand.
    """
    previous_was_blank = False

    for paragraph in document.paragraphs:
        if _is_effectively_empty(paragraph):
            previous_was_blank = True
            continue

        if previous_was_blank:
            _set_paragraph_from_margin(
                paragraph,
                document,
                use_normal_no_indent=False,
            )

        previous_was_blank = False

def _set_paragraph_from_margin(
    paragraph: Paragraph,
    document: Document,
    *,
    use_normal_no_indent: bool = False,
) -> None:
    """Fjern avsnittsinnrykk, og bruk eventuelt NormalNoIndent-stilen."""
    if use_normal_no_indent:
        try:
            paragraph.style = document.styles["NormalNoIndent"]
        except KeyError:
            # Direkte formatering nedenfor gir riktig marg også med en eldre mal.
            pass

    paragraph.paragraph_format.left_indent = Pt(0)
    paragraph.paragraph_format.right_indent = Pt(0)
    paragraph.paragraph_format.first_line_indent = Pt(0)


def _iter_table_paragraphs(table):
    """Yield alle avsnitt i en tabell, også i nestede tabeller."""
    seen_cells = set()
    for row in table.rows:
        for cell in row.cells:
            cell_element = cell._tc
            if cell_element in seen_cells:
                continue
            seen_cells.add(cell_element)

            yield from cell.paragraphs
            for nested_table in cell.tables:
                yield from _iter_table_paragraphs(nested_table)


def _set_tables_from_margin(document: Document) -> None:
    """Plasser tabeller ved margen og bruk NormalNoIndent i tabellceller."""
    for table in document.tables:
        tbl_pr = table._tbl.tblPr
        tbl_ind = tbl_pr.find(qn("w:tblInd"))
        if tbl_ind is None:
            tbl_ind = OxmlElement("w:tblInd")
            tbl_pr.append(tbl_ind)
        tbl_ind.set(qn("w:w"), "0")
        tbl_ind.set(qn("w:type"), "dxa")

        for paragraph in _iter_table_paragraphs(table):
            _set_paragraph_from_margin(
                paragraph,
                document,
                use_normal_no_indent=True,
            )


def _numbering_level(document: Document, num_id: str, level: str):
    """Finn w:lvl som et konkret numId/ilvl peker på."""
    try:
        numbering = document.part.numbering_part.element
    except (AttributeError, KeyError):
        return None

    abstract_id = None
    for num in numbering.findall(qn("w:num")):
        if num.get(qn("w:numId")) != num_id:
            continue
        abstract_ref = num.find(qn("w:abstractNumId"))
        if abstract_ref is not None:
            abstract_id = abstract_ref.get(qn("w:val"))
        break

    if abstract_id is None:
        return None

    for abstract_num in numbering.findall(qn("w:abstractNum")):
        if abstract_num.get(qn("w:abstractNumId")) != abstract_id:
            continue
        for lvl in abstract_num.findall(qn("w:lvl")):
            if lvl.get(qn("w:ilvl")) == level:
                return lvl
    return None


def _set_level_zero_lists_from_margin(document: Document) -> None:
    """
    Flytt markøren for nivå-0-lister til venstremargen.

    Pandoc legger vanligvis inn left=720/hanging=480 i numbering.xml. Direkte
    w:ind på avsnittet har høyere prioritet. Ved å sette left lik hanging blir
    markørposisjonen left-hanging = 0, mens brutte linjer fortsatt flukter med
    den første tekstlinjen. Nivå 1 og dypere beholdes uendret.
    """
    paragraphs = list(document.paragraphs)
    for table in document.tables:
        paragraphs.extend(_iter_table_paragraphs(table))

    for paragraph in paragraphs:
        p_pr = paragraph._p.pPr
        if p_pr is None:
            continue
        num_pr = p_pr.find(qn("w:numPr"))
        if num_pr is None:
            continue

        ilvl = num_pr.find(qn("w:ilvl"))
        num_id_element = num_pr.find(qn("w:numId"))
        level = ilvl.get(qn("w:val")) if ilvl is not None else "0"
        if level != "0" or num_id_element is None:
            continue

        num_id = num_id_element.get(qn("w:val"))
        lvl = _numbering_level(document, num_id, level)

        hanging = 360
        if lvl is not None:
            lvl_p_pr = lvl.find(qn("w:pPr"))
            lvl_ind = lvl_p_pr.find(qn("w:ind")) if lvl_p_pr is not None else None
            if lvl_ind is not None:
                try:
                    hanging = max(1, int(lvl_ind.get(qn("w:hanging"), hanging)))
                except (TypeError, ValueError):
                    hanging = 360

        ind = p_pr.find(qn("w:ind"))
        if ind is None:
            ind = OxmlElement("w:ind")
            p_pr.append(ind)
        ind.set(qn("w:left"), str(hanging))
        ind.set(qn("w:hanging"), str(hanging))
        ind.attrib.pop(qn("w:firstLine"), None)

        tabs = p_pr.find(qn("w:tabs"))
        if tabs is None:
            tabs = OxmlElement("w:tabs")
            p_pr.append(tabs)
        num_tab = None
        for tab in tabs.findall(qn("w:tab")):
            if tab.get(qn("w:val")) == "num":
                num_tab = tab
                break
        if num_tab is None:
            num_tab = OxmlElement("w:tab")
            tabs.append(num_tab)
        num_tab.set(qn("w:val"), "num")
        num_tab.set(qn("w:pos"), str(hanging))


def _set_marked_blocks_from_margin(document: Document) -> None:
    """Normaliser ramme-, bilde- og ordlistebolker med omsluttende blanklinjer."""
    paragraphs = list(document.paragraphs)
    normalized = [" ".join((p.text or "").split()).casefold() for p in paragraphs]

    def is_blank(index: int) -> bool:
        return not normalized[index]

    def is_opening(text: str) -> bool:
        return text.startswith((
            "ramme:",
            "bilde:",
            "ramme/bilde:",
            "ordliste:",
            "ordforklaringer:",
            "gloser:",
            "[ramme start",
            "[bilde start",
        ))

    def is_closing(text: str) -> bool:
        return text.startswith((
            "[ramme slutt]",
            "[bilde slutt]",
            "ramme slutt",
            "bilde slutt",
            "ordliste slutt",
            "ordforklaringer slutt",
            "gloser slutt",
        ))

    i = 0
    while i < len(paragraphs):
        if not is_opening(normalized[i]):
            i += 1
            continue

        glossary_block = normalized[i].startswith((
            "ordliste:",
            "ordforklaringer:",
            "gloser:",
        ))
        start = i - 1 if i > 0 and is_blank(i - 1) else i
        end = i

        # Rammer avsluttes normalt med [Ramme slutt]. For en enkeltstående
        # Bilde:-bolk uten sluttmarkør brukes neste tomme avsnitt som grense.
        closing_index = None
        next_blank = None
        for j in range(i + 1, len(paragraphs)):
            if is_closing(normalized[j]):
                closing_index = j
                break
            if next_blank is None and is_blank(j):
                next_blank = j
            if j > i + 1 and is_opening(normalized[j]):
                break

        if closing_index is not None:
            end = closing_index
            if end + 1 < len(paragraphs) and is_blank(end + 1):
                end += 1
        elif next_blank is not None:
            end = next_blank

        for index in range(start, end + 1):
            marker_or_blank = (
                is_blank(index)
                or is_opening(normalized[index])
                or is_closing(normalized[index])
            )
            _set_paragraph_from_margin(
                paragraphs[index],
                document,
                use_normal_no_indent=(glossary_block or marker_or_blank),
            )

        i = end + 1


def _set_senior_image_layout(document: Document, grade: int) -> None:
    """Image text: margin for labels/lists; TOINN for continuation prose.

    A single caption is flush; when both explanation and caption are present,
    caption starts two spaces in. Lists retain their existing list layout.
    """
    if grade < 8:
        return

    paragraphs = list(document.paragraphs)
    for i, paragraph in enumerate(paragraphs):
        text = (paragraph.text or '').strip()
        if not text.casefold().startswith('bilde:'):
            continue
        _set_paragraph_from_margin(paragraph, document, use_normal_no_indent=True)
        j = i + 1
        while j < len(paragraphs) and paragraphs[j].text.strip():
            p = paragraphs[j]
            t = p.text.strip()
            low = t.casefold()
            if low.startswith('forklaring:') or low.startswith('beskrivelse:'):
                _set_paragraph_from_margin(p, document, use_normal_no_indent=True)
            elif low.startswith('bildetekst:'):
                _set_paragraph_from_margin(p, document, use_normal_no_indent=True)
                has_explanation = any(paragraphs[k].text.strip().casefold().startswith(('forklaring:', 'beskrivelse:')) for k in range(i+1,j))
                if has_explanation and not p.text.startswith('  '):
                    p.text = '  ' + p.text.lstrip()
                elif not has_explanation:
                    p.text = p.text.lstrip()
            elif p.text.startswith('  '):
                _set_paragraph_from_margin(p, document, use_normal_no_indent=True)
            j += 1


def _set_glossary_entries_layout(document: Document, grade: int) -> None:
    """
    Fjern det interne oppslagsprefikset og formater ordforklaringene.

    Trinn 1–5:  fra marg uten innrykk.
    Fra trinn 6: fra marg med 360 twips hengende innrykk og uten listetegn.
    """
    paragraphs = list(document.paragraphs)
    for table in document.tables:
        paragraphs.extend(_iter_table_paragraphs(table))

    for paragraph in paragraphs:
        if GLOSSARY_ENTRY_PREFIX not in (paragraph.text or ""):
            continue

        # Oppslagslinjene er ren tekst etter dl-konverteringen. Å sette text på
        # nytt fjerner prefikset sikkert også dersom Pandoc har delt det i runs.
        paragraph.text = paragraph.text.replace(GLOSSARY_ENTRY_PREFIX, "", 1)
        _set_paragraph_from_margin(
            paragraph,
            document,
            use_normal_no_indent=True,
        )

        if grade >= 6:
            paragraph.paragraph_format.left_indent = Pt(
                GLOSSARY_HANGING_INDENT_PT
            )
            paragraph.paragraph_format.first_line_indent = Pt(
                -GLOSSARY_HANGING_INDENT_PT
            )


def _set_page_and_exercise_numbers_from_margin(document: Document) -> None:
    """Plasser sidetall (--- N) og oppgavenummer (>>> N.) helt fra margen."""
    patterns = (
        re.compile(r'^\s*---\s+\S+'),
        re.compile(r'^\s*>>>\s+\d+(?:[.,]\d+)*\.'),
    )

    paragraphs = list(document.paragraphs)
    for table in document.tables:
        paragraphs.extend(_iter_table_paragraphs(table))

    for paragraph in paragraphs:
        text = paragraph.text or ''
        if any(pattern.match(text) for pattern in patterns):
            _set_paragraph_from_margin(
                paragraph,
                document,
                use_normal_no_indent=True,
            )
            # Dersom Pandoc har arvet nummerering fra en liste, fjern den.
            p_pr = paragraph._p.pPr
            if p_pr is not None:
                num_pr = p_pr.find(qn('w:numPr'))
                if num_pr is not None:
                    p_pr.remove(num_pr)


def normalize_margin_layout(
    document: Document,
    logger: logging.Logger,
    grade: Optional[int] = None,
) -> Document:
    """Samlet etterbehandling for tabeller, nivå-0-lister og markerte bolker."""
    effective_grade = grade if grade is not None else DEFAULT_GRADE
    logger.info(
        "Normaliserer tabeller, nivå-0-lister og ramme-/bilde-/ordforklaringsbolker fra marg"
    )
    _set_tables_from_margin(document)
    _set_marked_blocks_from_margin(document)
    _set_senior_image_layout(document, effective_grade)
    _set_glossary_entries_layout(document, effective_grade)
    # Kjøres etter generell listejustering slik at disse spesiallinjene alltid
    # ender helt fra margen og uten arvet Word-nummerering.
    _set_level_zero_lists_from_margin(document)
    _set_page_and_exercise_numbers_from_margin(document)
    return document


def _derive_title(document: Document) -> str:
    """Hent tittel fra core properties eller første avsnitt med stil 'Title'."""
    title = document.core_properties.title or ""
    if not title:
        for p in document.paragraphs:
            try:
                if p.style and p.style.name.lower() == "title" and p.text.strip():
                    title = p.text.strip()
                    break
            except Exception:
                pass

    if title:
        # fjern evt. trailing språk-ord
        pattern = r"\s+(" + "|".join(map(re.escape, LANGUAGES_TRAILING)) + r")$"
        title = re.sub(pattern, "", title, flags=re.IGNORECASE).strip()
    return title or "Dokument"


# ==============================================================================
# 4) HØYNIVÅ-PIPELINE
# ==============================================================================

def _read_soup_from_input(input_path: Path) -> tuple[BeautifulSoup, Path]:
    """
    Les XHTML enten fra en fil eller fra en mappe med utpakket EPUB.
    Returnerer (soup, faktisk_xhtml_fil).
    """
    if input_path.is_dir():
        # Finn første .xhtml som ikke er nav.xhtml
        xhtml_files = [p for p in input_path.glob("*.xhtml") if p.name.lower() != "nav.xhtml"]
        if not xhtml_files:
            raise FileNotFoundError(f"Fant ingen .xhtml i {input_path}")
        if len(xhtml_files) > 1:
            args.logger.warning("Fant flere .xhtml-filer, bruker: %s", xhtml_files[0].name)
        target = xhtml_files[0]
    else:
        target = input_path
        if target.suffix.lower() not in {".xhtml", ".html", ".htm"}:
            args.logger.warning("Input ser ikke ut som XHTML/HTML: %s", target.name)

    with target.open("rb") as f:
        data = f.read()
    # bruk XML-parser, men tåler HTML
    soup = BeautifulSoup(data, "lxml-xml")
    return soup, target


def xhtml_to_docx(
    xhtml_bytes: bytes,
    output_filename: str = "output.docx",
    *,
    reference_docx: Optional[Path] = None,
    pandoc_args: Sequence[str] = (),
    grade: Optional[int] = None,
    mathematics: bool = False,
    science: bool = False,
    toc_levels: Optional[int] = None,
    no_excel: bool = False,
) -> bytes:
    """API: bytes → bytes."""
    prep_args = PrepareArgs(
        mathematics=mathematics,
        science=science,
        verbose=False,
        toc_levels=toc_levels,
        grade=grade,
        no_excel=no_excel,
    )
    pandoc_opts = PandocOptions(reference_docx=reference_docx, extra_flags=pandoc_args)
    clean_args = CleanArgs(grade=grade)

    with tempfile.TemporaryDirectory(prefix="bok_to_docx_") as tmp_s:
        tmp = Path(tmp_s)
        in_html = tmp / "in.xhtml"
        in_html.write_bytes(xhtml_bytes)

        # prepare
        soup = BeautifulSoup(xhtml_bytes, "lxml-xml")
        prepared = prepare_soup(soup, args, args.logger)
        prepared_html = tmp / "prepared.xhtml"
        prepared_html.write_text(str(prepared), encoding="utf-8")

        # pandoc
        out_docx = tmp / Path(output_filename).name
        run_pandoc(prepared_html, out_docx, pandoc_opts)
        if not out_docx.exists():
            raise RuntimeError("Pandoc genererte ingen DOCX")

        # clean
        doc = Document(str(out_docx))
        doc = clean_document(doc, clean_args, args.logger)
        doc = remove_duplicate_opening_title(doc)
        doc = normalize_margin_layout(doc, args.logger, grade=grade)
        doc = format_about_book_from_margin(doc)

        # output as bytes
        final_docx = tmp / Path(output_filename).name
        doc.save(str(final_docx))
        return final_docx.read_bytes()


# New convert method
def convert(args):
    pandoc_opts = PandocOptions(reference_docx=get_ref_doc(args), extra_flags=args.pandoc_args or ())
    clean_args = CleanArgs(grade=args.grade)

    # --- INPUT: fil, mappe, eller stdin
    if args.input == "-":
        data = sys.stdin.buffer.read()
        if not data:
            args.logger.error("Ingen data på stdin.")
            return 2
        out_name = args.output.name if args.output else "output.docx"
        try:
            out_bytes = xhtml_to_docx(
                data, out_name,
                reference_docx=args.reference_docx,
                pandoc_args=args.pandoc_args or (),
                grade=args.grade,
                mathematics=args.mathematics,
                science=args.science,
                toc_levels=args.toc_levels,
                no_excel=args.no_excel,
            )
        except Exception as e:
            args.logger.error("Konvertering feilet: %s", e)
            return 1

        if args.stdout:
            sys.stdout.buffer.write(out_bytes)
        else:
            if not args.output:
                args.logger.error("Må angi -o/--output hvis ikke --stdout.")
                return 2
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(out_bytes)
            args.logger.info("Skrev %s (%.1f KB)", args.output, len(out_bytes)/1024.0)
        return 0

    # Fil eller mappe
    in_path = Path(args.input).expanduser().resolve()
    if not in_path.exists():
        args.logger.error("Finner ikke input: %s", in_path)
        return 2

    try:
        soup, actual_xhtml = _read_soup_from_input(in_path)
    except Exception as e:
        args.logger.error("Klarte ikke lese input: %s", e)
        return 2

    def find_production_number(soup: BeautifulSoup) -> str:
        """Finn produksjonsnummer fra metadata eller filnavn."""
        # Prøv metadata først
        meta = soup.find("meta", attrs={"name": "production_number"})
        if meta and meta.has_attr("content"):
            return meta["content"].strip()
        # Fallback: bruk filstamme
        return actual_xhtml.stem

    with tempfile.TemporaryDirectory(prefix="bok_to_docx_") as tmp_s:
        tmp = Path(tmp_s)

        # prepare
        production_number = find_production_number(soup)
        prepared = prepare_soup(soup, args)
        prepared_html = tmp / (actual_xhtml.name if actual_xhtml.suffix else "prepared.xhtml")
        prepared_html.write_text(str(prepared), encoding="utf-8")

        # pandoc
        out_docx_tmp = tmp / ((args.output.name if args.output else actual_xhtml.with_suffix(".docx").name))
        try:
            run_pandoc(args, prepared_html, out_docx_tmp, pandoc_opts)
        except Exception as e:
            args.logger.error("Pandoc feilet: %s", e)
            return 1

        if not out_docx_tmp.exists():
            args.logger.error("Ingen DOCX fra pandoc.")
            return 1

        # clean
        try:
            doc = Document(str(out_docx_tmp))
            doc = clean_document(doc, args)
            doc = remove_duplicate_opening_title(doc)
            doc = normalize_margin_layout(doc, args.logger, grade=args.grade)
            doc = format_about_book_from_margin(doc)
        except Exception as e:
            args.logger.error("DOCX-etterbehandling feilet: %s", e)
            return 1

        '''
        # Bestem endelig output
        if args.stdout:
            bio = io.BytesIO()
            doc.save(bio)
            sys.stdout.buffer.write(bio.getvalue())
            return 0
        '''

        '''
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            doc.save(str(args.output))
            args.logger.info("Skrev %s", args.output)
            return 0
        '''

        # Default: lag mappen output/<production_number>/, og lag filnavn ut fra tittel
        #production_number = actual_xhtml.stem
        '''
        out_dir = OUTPUT_DIR / production_number
        if out_dir.exists():
            args.logger.info("Fjerner gammel output-mappe: %s", out_dir)
            shutil.rmtree(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        '''

        '''
        if args.job_dir.exists():
            args.logger.info("Fjerner gammel output-mappe: %s", args.job_dir)
            shutil.rmtree(args.job_dir)
        args.job_dir.mkdir(parents=True, exist_ok=True)
        '''

        title = _derive_title(doc)
        #final_name = f"{title} {actual_xhtml.with_suffix('.docx').name}"
        #final_path = out_dir / final_name
        final_name = f"{args.production_number}.docx"
        final_path = args.job_dir / final_name
        print(f'Final path will be: {final_path}')
        doc.save(str(final_path))
        args.logger.info("Skrev %s", final_path)
        args.logger.info(f'Final path: {final_path}')
        args.logger.info("Tittel hentet fra dokumentet: %s", title)
        return 0

    args.logger.error("Ukjent kommando.")
    return 2

# ==============================================================================
# 5) CLI
# ==============================================================================

# -----------------------------------------------------------------------------
# Logger (for CLI)
# -----------------------------------------------------------------------------

def make_logger() -> logging.Logger:
    """Logger som skriver til stdout (synlig i docker logs)."""
    logger = logging.getLogger("bok_to_docx")
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        h = logging.StreamHandler()
        h.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
        logger.addHandler(h)
    return logger

def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bok_to_docx",
        description="Konverter XHTML/utpakket EPUB → DOCX i én fil (prepare + pandoc + clean).",
    )

    # Generelle flagg
    p.add_argument(
        "--log-level",
        default=DEFAULT_LOG_LEVEL,
        choices=["CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"],
        help="Loggnivå",
    )
    p.add_argument(
        "--reference-docx",
        type=Path,
        default=None,
        help="Referanse-DOCX (overstyrer static/TEMPLATE_SENIOR.docx).",
    )
    p.add_argument(
        "--pandoc-args",
        action="append",
        default=[],
        help="Ekstra flagg til pandoc (kan gjentas).",
    )
    p.add_argument(
        "--stdout",
        action="store_true",
        help="Skriv DOCX til stdout (binær).",
    )
    p.add_argument(
        "--no-excel",
        action="store_true",
        help="Skru av Excel-uttrekk av tabeller.",
    )

    # prepare/clean-relaterte flagg
    p.add_argument(
        "-g", "--grade",
        type=int,
        help="Klassetrinn (påvirker fontvalg i DOCX).",
    )
    p.add_argument(
        "-m", "--mathematics",
        action="store_true",
        help="Matematikkbok (hint).",
    )
    p.add_argument(
        "-s", "--science",
        action="store_true",
        help="Naturfag (hint).",
    )
    p.add_argument(
        "-t", "--toc-levels",
        type=int,
        help="Antall TOC-nivåer (hint til prepare).",
    )
    p.add_argument(
        "input",
        help="XHTML/HTML-fil, mappe (utpakket EPUB), eller '-' for stdin.",
    )
    p.add_argument(
        "-o", "--output",
        type=Path,
        help="Output .docx",
    )
    p.add_argument(
        "--job_dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Output-mappe for genererte DOCX-filer (standard: artifacts).",
    )
    p.add_argument(
            '--production_number',
            type=str,
            default=DEFAULT_PRODUCTION_NUMBER,
            help='Produksjonsnummer for output DOCX-filen (standard: production_number)',
        )
    p.add_argument('-b',
                        '--book',
                        help = 'The statpub_to_bok converter methods are to be used',
                        action = 'store_true')
    p.add_argument(
                        '-v', '--verbose',
                        action='count',
                        default=0,
                        help='Increase verbosity: -v=INFO, -vv=DEBUG'
                        )
    p.add_argument('-p',
                        '--p-length',
                        help = 'The maximum length of a small paragraph',
                        type = int)
    p.add_argument('-l',
                        '--link_footnotes',
                        help = 'Link to footnotes in the text',
                        action = 'store_true')
    p.add_argument('-i',
                        '--index',
                        help = 'Remove indexes',
                        action = 'store_true')

    return p

def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_arg_parser().parse_args(argv)
    args.logger = make_logger()

    result = convert(args)
    

    print('Testing production number output:')
    print(args.production_number)

    match result:
        case 0:
            args.logger.info("Ferdig uten feil.")
        case 1:
            args.logger.error("Ferdig med feil under konvertering.")
        case 2:
            args.logger.error("Ferdig med feil i input eller parametre.")
        case _:
            args.logger.error("Ukjent avslutningskode: %s", result)

if __name__ == "__main__":
    raise SystemExit(main())
