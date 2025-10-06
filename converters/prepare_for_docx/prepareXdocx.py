'''
Structure information classes:
    - structureinformation-table
'''

# IMPORTS
# =======

from os             import listdir, path, makedirs
from shutil         import copyfile, rmtree, copytree
from logging        import getLogger, INFO, DEBUG
from argparse       import ArgumentParser
from bs4            import BeautifulSoup, NavigableString, Comment
from pandas         import DataFrame

import re

# STATIC VARIABLES
# ================

STATIC_DIR = path.join(path.dirname(path.abspath(__file__)), 'static')
OUTPUT_DIR = path.join(path.dirname(path.abspath(__file__)), 'output')

EXCEL_DIR       = 'Excel'
SMALL_P_LENGTH  = 10000000       # TODO: check length
DEFAULT_GRADE   = 8
EMPTY           = 'EMPTY_LINE'
NOINDENT        = 'NOINDENT'
LISTUNSTYLED    = 'LISTUNSTYLED'
TOINN           = 'TOINN'
GLOSSARY_CLASS  = 'glossary'
ASIDE_CLASSES   = [
        'generisk-ramme',
        'ramme bg-red',
        'ramme bg-blue',
        'ramme bg-yellow',
        'ramme bg-gray',
        'ramme bg-beige',
        ]

STRUCTURE_HEADING_SMALL     = 20
STRUCTURE_GLOSSARY_SMALL    = 400
STRUCTURE_FRAME_HEADING     = 'Ramme'
MAX_TABLE_WIDTH_CHARS       = 54
NUMERIC_THRESHOLD           = 0.7       # Percentage threshold to determine if a table is "numeric-heavy"

# FUNCTIONS
# =========

def get_table_width_chars(table):
    """
    Estimates the width of a table based on the number of columns and text content.
    """
    max_columns = 0

    for row in table.find_all("tr"):
        cells = row.find_all(["td", "th"])
        max_columns = max(max_columns, len(cells))  # Count columns

    return max_columns * 10  # Approximate character width per column

'''
def is_numeric_table(table):
    """
    Determines if a table contains a high percentage of numeric values.
    """
    num_cells = 0
    num_numeric = 0
    numeric_pattern = re.compile(r"^-?\d+(\.\d+)?$")  # Matches integers and decimals

    for row in table.find_all("tr"):
        for cell in row.find_all(["td", "th"]):
            num_cells += 1
            cell_text = cell.get_text(strip=True)
            if numeric_pattern.fullmatch(cell_text):  # Check if cell contains only numbers
                num_numeric += 1

    if num_cells == 0:
        return False  # Avoid division by zero

    return (num_numeric / num_cells) >= NUMERIC_THRESHOLD  # Returns True if numeric-heavy
'''

def is_excel_like_table(table):
    """
    Checks if a BeautifulSoup <table> element follows the "Excel-like" structure:
    1. The upper-left cell (row 0, column 0) is empty.
    2. The first row (excluding the first cell) contains "A", "B", "C", etc.
    3. The first column (excluding the first cell) contains "1", "2", "3", etc.
    
    :param table: BeautifulSoup Tag object representing a <table>.
    :return: True if the table follows the Excel structure, otherwise False.
    """

    if not table or table.name != "table":
        return False  # Input must be a <table> element

    rows = table.find_all("tr")
    if len(rows) < 2:  # Needs at least header + one row
        return False

    # Extract all cells from first row and first column
    first_row_cells = rows[0].find_all(["td", "th"])
    first_col_cells = [row.find(["td", "th"]) for row in rows[1:]]

    # 1) Check if upper-left cell is empty
    if first_row_cells and first_row_cells[0].text.strip():
        return False

    # 2) Check first row values (A, B, C, ...)
    expected_columns = list(string.ascii_uppercase)[:len(first_row_cells)-1]  # Generate A, B, C...
    actual_columns = [cell.text.strip() for cell in first_row_cells[1:]]

    if actual_columns != expected_columns:
        return False

    # 3) Check first column values (1, 2, 3, ...)
    expected_rows = [str(i+1) for i in range(len(first_col_cells))]
    actual_rows = [cell.text.strip() for cell in first_col_cells if cell]

    if actual_rows != expected_rows:
        return False

    return True


def prepare(soup, args, logger):

    grade = args.grade if args.grade else DEFAULT_GRADE

    # 4.12 Sidetall
    # -------------
    # It should anyway remain pagebreak instead of being a paragraph
    logger.info('4.12 Sidetall')
    for pagebreak in soup(attrs={'epub:type': 'pagebreak'}):
        insert_after_element = pagebreak
        p = soup.new_tag('p')
        if 'title' in pagebreak.attrs:
            p.string = f'--- {pagebreak["title"]}'
        elif 'id' in pagebreak.attrs:
            p.string = f'--- {pagebreak["id"].split("-")[-1]}'

        # TODO: set to sentence level instead of paragraph level - Tricky
        logger.debug(f'Adding page number: {p.string}')
        for parent in pagebreak.parents:
            if parent.name == 'p':
                insert_after_element = parent
                break

        insert_after_element.insert_after(p)
        pagebreak.decompose()

        logger.debug(f'Page number added after {insert_after_element.name}')
        if p.parent.name == 'section':
            if (element := p.find_next_sibling()):
                if element.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                    if not (p_previous_sibling := p.find_previous_sibling()):
                        if ((parent_previous_sibling := p.parent.find_previous_sibling()) and
                            parent_previous_sibling.name == 'section'):
                            parent_previous_sibling.append(p)
                        else:
                            p.parent.insert_before(p)

    # 4.13 Avsnitt
    # ------------
    # Large paragraphs
    logger.info('4.13 Avsnitt - store avsnitt')
    for p in soup('p'):
        if len(p.get_text()) > SMALL_P_LENGTH:
            empty_p = soup.new_tag('p')
            empty_p.string = EMPTY
            p.insert_before(empty_p)
        # 4.13 I leselistbøker markeres vanlige avsnitt i løpende tekst med ny linje med to tegns innrykk (eller 0,44 inn) #56
        # TODO: This does not catch all cases
        if (not (p.get_text().startswith(TOINN) or p.get_text().startswith('--- ')) and
              (previous_sibling := p.previous_sibling) and
              previous_sibling.name == 'p' and
              not (previous_sibling.get_text().startswith('--- ') or previous_sibling.get_text().startswith('-- '))):
            p.insert(0, TOINN)

    # After EMPTY, the paragraph starts from NOINDENT
    # -> below 4.14

    '''
    logger.info('Adding NOINDENT after EMPTY')
    for paragraph in soup('p'):
        if (previous_sibling := paragraph.previous_sibling):
            # NOINDENT after heading
            if previous_sibling.name in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                paragraph.insert(0, NOINDENT)
            # NOINDENT after pagebreak
            elif previous_sibling.get_text().startswith('--- '):
                paragraph.insert(0, NOINDENT)
            # NOINDENT after image explanation -> 8.5
    '''

    # 4.14 Blank linje
    # ----------------
    # Innholdsfortegnelsen settes inn automatisk, med blank linje over Innhold
    logger.info('4.14 Innholdsfortegnelsen settes inn automatisk, med blank linje over Innhold')
    if (toc := soup.find('section', attrs={'epub:type': 'frontmatter toc'})):
        empty_p = soup.new_tag('p')
        empty_p.string = EMPTY
        if (previous_sibling := toc.previous_sibling):
            previous_sibling.append(empty_p)

    # Bruk blank linje over alle overskrifter,
    # unntatt der flere overskrifter følger
    # rett etter hverandre eller rett etter
    # sidetallet. I slike tilfeller legges
    # blank linje bare over den første
    # overskriften eller sidetallet.
    # TODO: Implement
    #  4.14 Bruk blank linje over alle overskrifter, unntatt der flere overskrifter følger rett
    # etter hverandre eller rett etter sidetallet. I slike tilfeller legges blank linje bare over
    # den første overskriften eller sidetallet. #5
    # The issue of heading after pagebreak is handled in clean_docx
    logger.info('4.14 Bruk blank linje over alle overskrifter')
    for h in soup(re.compile(r'h[1-6]')):
        if ((previous_sibling := h.previous_sibling) and
            previous_sibling.name == 'p' and
            previous_sibling.get_text() == EMPTY):
                continue
        elif ((previous_p := h.find_previous('p')) and
              previous_p.get_text().startswith('--- ') and
              (sibling_before := previous_p.previous_sibling) and
              not (sibling_before.name == 'p' and sibling_before.get_text() == EMPTY)):
            empty_p = soup.new_tag('p')
            empty_p.string = EMPTY
            previous_p.insert_before(empty_p)
        else:
            empty_p = soup.new_tag('p')
            empty_p.string = EMPTY
            h.insert_before(empty_p)

    # Det skal være blank linje foran oppgavetegnet 
    # (>>>), unntatt når oppgaven begynner like etter
    # en overskrift. Det skal også være blank linje
    # etter oppgaven.
    # TODO: Move to 6.1
    logger.info('4.1 Det skal være blank linje foran oppgavetegnet')
    for p in soup('p'):
        if p.get_text().startswith('>>>'):
            if (previous_sibling := p.previous_sibling):
                if previous_sibling.name not in ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']:
                    empty_p = soup.new_tag('p')
                    empty_p.string = EMPTY
                    previous_sibling.append(empty_p)
            if (next_sibling := p.next_sibling): # TODO: Check if this works
                if next_sibling.name != 'p':
                    empty_p = soup.new_tag('p')
                    empty_p.string = EMPTY
                    p.insert_after(empty_p)

    # Lister avsluttes med en blank linje

    # Blank before and after structure information
    # -> 4.17

    # Blank before and after task
    # -> 6.1

    # 4.13 - NOINDENT after EMPTY
    # ---------------------------
    '''
    logger.info('Adding NOINDENT after EMPTY')
    for paragraph in soup('p'):
        if paragraph.get_text() == EMPTY:
            paragraph.insert(0, NOINDENT)
    '''

    # 4.16 Utheving
    # -------------
    logger.info('4.16 Utheving')
    for emphasis in soup(['em', 'i', 'strong', 'b']):
        if not args.mathematics:
            emphasis.insert(0, NavigableString('_'))
            emphasis.append(NavigableString('_'))
        emphasis.unwrap()

    # 4.17 Strukturinformasjon
    # ------------------------
    # TODO: Check which types of structure information should be present in other formats
    logger.info('4.17 Strukturinformasjon')
    structure_types = {}
    
    # 4.17 Strukturinformasjon legges inn når det er nødvendig å skille ut elementer som
    # er markert på en spesiell måte i originalboka. Dette kan for eksempel være rammetekster,
    # margtekster, tabeller, ordlister, oppgaver eller bilder. #40
    logger.info('''
    4.17 Strukturinformasjon legges inn når det er nødvendig å skille ut elementer som er 
    markert på en spesiell måte i originalboka. Dette kan for eksempel være rammetekster, 
    margtekster, tabeller, ordlister, oppgaver eller bilder. #40
    ''')
    for aside in soup('aside', attrs={'class':'text-box'}):
        textbox_start           = soup.new_tag('p')
        textbox_stop            = soup.new_tag('p')
        textbox_start.string    = 'Ramme:'
        textbox_stop.string     = 'Ramme slutt'
        aside.insert(0, textbox_start)
        aside.insert(-1, textbox_stop)


    for class_name in ASIDE_CLASSES:
        if ((elements := [e for e in soup() if class_name in e.get('class', [])])                       and
            (headings := [element.find().get_text().strip() for element in elements if element.find()]) and 
            all(headings)                                                                               and 
            len(headings) > 1                                                                           and 
            len(list(set([heading for heading in headings]))) == 1):

            structure_types[class_name] = headings[0]

            for element in elements:
                # Add structure class to element
                if 'structure' not in element.get('class', []):
                    element['class'] = element.get('class', [])
                    if isinstance(element['class'], str): 
                        element['class'] = [element['class']]
                    element['class'].append('structure')
                # Handle layout TODO: Check if this should be moved to statpub_to_bok
                if (heading := element.find()):
                    if not STRUCTURE_FRAME_HEADING in heading.get_text().strip():
                        if (len(heading.get_text()) < STRUCTURE_HEADING_SMALL or 
                            bool(re.fullmatch(r'h[1-6]', heading.name, re.IGNORECASE))):
                            heading.insert(0, NavigableString(f'{STRUCTURE_FRAME_HEADING}: '))
                        else:
                            start_p = soup.new_tag('start_p')
                            start_p['class'] = 'structure-heading'
                            start_p.string = f'{STRUCTURE_FRAME_HEADING}:'
                            heading.insert_before(start_p)
                        # TODO: create conditions for excluding end_p
                        if not len(heading.find_all_next()) <= 1:
                            end_p = soup.new_tag('p') 
                            end_p.string = f'{STRUCTURE_FRAME_HEADING} slutt'
                            element.append(end_p)
                all_text = element.get_text().strip()
                # 4.14 Blank linje skal også legges inn før og etter strukturinformasjon #6
                if (previous_sibling := element.previous_sibling):
                    if previous_sibling.name in ['span', 'div'] and previous_sibling.get('epub:type', []) == 'pagebreak':
                        continue
                    elif (previous_sibling.get_text().strip() == EMPTY):
                        continue
                    else:
                        empty_p = soup.new_tag('p')
                        empty_p.string = EMPTY
                        element.insert_before(empty_p)
            # #43: must be done manually
        
    
    # 4.17.1 Strukturinformasjon ved tabeller og tabell-liknende oppsett #11
    # TODO: deal with turntables
    logger.info('4.17.1 Strukturinformasjon ved tabeller og tabell-liknende oppsett #11')

    for table in soup('table'):
        # Find length and width
        width       = sum(int(cell.get('colspan', 1)) for cell in table('tr')[0](['th', 'td']))
        length      = len(table.find_all('tr'))
        p           = soup.new_tag('p')
        p['class']  = 'structureinformation-table'
        p.string    = f'Tabell: {width} kolonner, {length} rader:'
        table.insert_before(p) # TODO: check table headings

    # 4.17.2 Strukturinformasjon ved lister med utgangspunkt i tabeller #9
    # TODO: Deal with tables that should be turned

    # 4.19 Statpeds produksjonsnummer #23
    logger.info(f'Statpeds produksjonsnummer #23')
    # TODO: implement

    # 5 Lister
    # ========

    # 5.1 Ordnede lister
    # ------------------
    # -> pandoc

    # 5.2 Punktlister
    # ---------------
    # -> pandoc

    # logger.info('4.14 Lister avsluttes med en blank linje')
    # TODO: if list is last in an aside, do NOT add empty line
    # TODO: CONTINUE HERE............
    logger.info('4.14 Lister avsluttes med en blank linje')
    for l in soup(['ul', 'ol']):
        if (next_sibling := l.next_sibling):
            if next_sibling.name != 'p' or next_sibling.get_text() != EMPTY:
                empty_p = soup.new_tag('p')
                empty_p.string = EMPTY
                l.insert_after(empty_p)
        if grade <= 7: # TODO: check if this could be done just by changing names of tags
            for ol in soup('ol'):
                start = int(ol.get('start', 1))
                for i, li in enumerate(ol.find_all("li"), start=0):
                    li.insert(0, f'{i + start}. ')
            for ul in soup('ul'):
                for li in ul.find_all("li"):
                    li.insert(0, '-- ')
            for li in soup('li'):
                li.insert(0, TOINN * (len([p for p in li.parents if p.name in ['ul', 'ol']])-1))
                li.append(NavigableString('\n'))
            for list_tag in soup(['ul', 'ol', 'li']):
                if list_tag.name in ['ul', 'ol']:
                    list_tag.name = 'section'
                    for attr in list_tag.attrs.values():
                        del list_tag[attr]
                    del list_tag['start']
                    del list_tag['type']
                    list_tag['class'] = 'list'
                elif list_tag.name == 'li':
                    list_tag.name = 'div'
                    list_tag['class'] = 'listitem'
                        
            '''
            section = soup.new_tag('section')
            try:
                for li in l('li'):
                    space = ''
                    li_parent = None
                    for parent in li.parents:
                        if parent.name in ['ul', 'ol']:
                            space += TOINN
                            if not li_parent:
                                li_parent = parent
                    if li_parent:
                        if li_parent.name == 'ul':
                            li.insert(0, f'{space}-- {li.get_text()}')
                        elif li_parent.name == 'ol':
                            li.insert(0, f'{space}{[c for c in li_parent.children if c.name=="li"].index(li)+1}. {li.get_text()}')
                    section.append(p)
                print(section.prettify())
                l.insert_after(section)
            except Exception as e:
                print(e)
                logger.error(f'Error in adding list items to section: {e}')
            for l in soup(['ul', 'ol']):
                l.decompose()
            '''

    # 5.3 Ordlister
    # -------------
    # TODO: Deal with cases of alphabetic section elements of glossary
    # 5.3 I noen tilfeller kan det være nyttig å legge til strukturinformasjon for å vise type liste. #44
    logger.info('5.3.1 I noen tilfeller kan det være nyttig å legge til strukturinformasjon for å vise type liste. #44')
    for dl in soup('dl'):
        if dl.parent.name == 'section': # and GLOSSARY_CLASS in dl.parent.get('class', []):
            if (heading := dl.parent.find(re.compile(r'h[1-6]', re.IGNORECASE))):
                h_text = heading.get_text().strip()
                if not bool(re.fullmatch(r'[a-zæøå]', h_text)) and not bool(re.fullmatch(r'[A-ZÆØÅ]', h_text)):
                    glossary = True if GLOSSARY_CLASS in dl.parent.get('class', []) else False
                    p_start = soup.new_tag('p')
                    p_start.string = 'Gloser:' if glossary else 'Ordliste:'
                    dl.insert_before(p_start)
                    if len(dl.get_text()) > STRUCTURE_GLOSSARY_SMALL:
                        p_stop = soup.new_tag('p')
                        p_stop.string = 'Gloser slutt' if glossary else 'Ordliste slutt'
                        dl.insert_after(p_stop)

    # 6.5 Kombinasjonsoppgaver/Krysskoblinger
    # ---------------------------------------
    # TODO: SMR 2.5.1.6 Match problems

    # 8.5 Bilder
    # ----------

    # 8.5.1 Bare beskrive #60
    # -----------------------
    # 8.5.1a. Beskrive med både bildetekst og forklaring #55
    # TODO: set standard for text in images
    logger.info('8.5.1a Beskrive med både bildetekst og forklaring #55')
    for figure in soup(['figure']):
        if (figcaption := figure.find('figcaption')):
            if (text := figcaption.get_text()):
                p = soup.new_tag('p')
                p.append(NavigableString(f'{TOINN}Bildetekst: {text}'))
                figure.insert_before(p)
                if p.parent.name == 'p':
                    p.parent.unwrap()
            figcaption.decompose()
        if figure.find('figure'):
            figure.name = 'section'
            p = soup.new_tag('p')
            p.string = 'Bildeserie:' # TODO: check term and make constant
            figure.insert(0, p)
        else:
            p = soup.new_tag('p')
            p.string = 'Bilde:'
            if (img := figure.find('img', attrs={'alt':True})):
                p.string += f' {img["alt"]}'
                img.decompose()
            figure.insert_before(p)
            if p.parent.name == 'p':
                p.parent.unwrap()

            # Text in images
            # TODO: define format

            if (aside := figure.find(attrs={'class': 'fig-desc'})):
                figure_paragraphs = aside('p')
                if len(figure_paragraphs) == 1:
                    figure_paragraphs[0].insert(0, NavigableString(f'{TOINN}Tekst i bildet: '))
                    figure.insert_before(figure_paragraphs[0])
                else:
                    for p in figure_paragraphs:
                        p.insert(0, TOINN + TOINN)
                    aside.insert(0, NavigableString(f'{TOINN}Tekst i bildet: '))
                aside.name = 'section'
                figure.insert_before(aside)

            figure.decompose()

    for img in soup('img'):
        p = soup.new_tag('p')
        p.string = 'Bilde:'
        p.append(NavigableString(f' {img["alt"]}'))
        img.insert_before(p)
        img.decompose()
        if p.parent.name == 'p':
            p.parent.unwrap()
    
            
    # 9.1 Word-tabeller kan brukes når det er plass til tabellen i bredden på en Word-side. #18
    too_wide_tables = []

    for idx, table in enumerate(soup.find_all("table")):
        table_width_chars = get_table_width_chars(table)

        if table_width_chars > MAX_TABLE_WIDTH_CHARS:
            too_wide_tables.append((idx + 1, table_width_chars, MAX_TABLE_WIDTH_CHARS))
            rows = []
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                rows.append([cell.get_text(strip=True) for cell in cells])

            df = DataFrame(rows)
            transposed_df = df.transpose()
            html_table = df.to_html(index=False, header=False)
            new_table = BeautifulSoup(html_table, "html.parser").find("table")
            if get_table_width_chars(new_table) < MAX_TABLE_WIDTH_CHARS: # TODO: test
                rows = new_table('tr')
                if (p := table.find_previous_sibling()) and p.name == 'p' and p.get_text().startswith('Tabell:'):
                    p.string = f'Tabell, snudd til {len(rows[0])} kolonner, {len(rows)} rader:'
                    table.replace_with(new_table)

    if too_wide_tables:
        logger.warning('The following tables are too wide for a Word page:')
        for table_idx, table_width, max_width in too_wide_tables:
            logger.warning(f" - Table {table_idx}: {table_width} characters > {max_width} (TOO WIDE)")
    else:
        logger.info('All tables fit within the Word page width.')

    # 9.2 Dersom tabellen går utover bredden til en Word-side, eller dersom den inneholder
    # mange tall som eleven skal gjøre beregninger med (for eksempel budsjett), kan tabellen
    # lages i Excel og settes inn i dokumentet som et objekt. #192
    logger.info('Creating Excel files for numeric-heavy tables')
    if args.excel_creation:
        # Create test table for Excel conversion at the end of the last section
        table = soup.new_tag("table")
        table['border'] = '1'
        table['style'] = 'width:100%'
        tbody = soup.new_tag("tbody")
        table.append(tbody)

        for i in range(5):
            tr = soup.new_tag("tr")
            for j in range(5):
                td = soup.new_tag("td")
                td.string = f"{i*j}"
                tr.append(td)
            tbody.append(tr)

        soup.find_all("section")[-1].append(table)
        
        # Excel folder inside output folder: 1) remove if exists, 2) create
        makedirs(path.join(OUTPUT_DIR, EXCEL_DIR), exist_ok=True)

        tables_to_replace = []

        for idx, table in enumerate(soup.find_all("table")):
            if is_excel_like_table(table):
                tables_to_replace.append((idx + 1, table))

        # Process each numeric-heavy table
        for table_idx, table in tables_to_replace:
            # Convert table to DataFrame
            rows = []
            for row in table.find_all("tr"):
                cells = [cell.get_text(strip=True) for cell in row.find_all(["td", "th"])]
                rows.append(cells)
            df = DataFrame(rows)

            # Save to Excel file
            excel_filename = f"table_{table_idx}.xlsx"
            df.to_excel(path.join(OUTPUT_DIR, EXCEL_DIR, excel_filename), index=False, header=False)

            # Create reference paragraph
            placeholder = soup.new_tag("p")
            placeholder.string = f'Excel regneark: {excel_filename}'

            # Insert placeholder before the table and replace the table
            table.insert_after(placeholder)

    # 9.3 Tabell som liste #77
    # Manually
    
    # 10.1 De enkelte ordene skal stå fra marg, etterfulgt av kolon, mellomrom og ordforklaringen. #16
    # ================================================================================================
    # Current solution: create a new paragraph for each word and explanation and insert it before the dl,
    # then remove the dl
    # Add "NOINDENT" to the start of the paragraph
    # TODO: Check if this is the best solution
    # TODO: Does pandoc insert dots between elements with no separator?
    logger.info('Adding NOINDENT to word explanations')
    for dl in soup('dl'):
        ul = soup.new_tag('ul')
        for dt, dd in zip(dl('dt'), dl('dd')):
            dt_span = soup.new_tag('span')
            dt_span.string = dt.get_text().replace(':','').strip()
            if 'lang' in dt.attrs:
                dt_span['lang'] = dt['lang']
            if 'xml:lang' in dt.attrs:
                dt_span['xml:lang'] = dt['xml:lang']
            dd_span = soup.new_tag('span')
            dd_span.string = dd.get_text().replace(':','').strip()
            if dd_span.string.startswith(' – '):
                dd_span.string = dd_span.string[3:] # TODO: debug
            if 'lang' in dd.attrs:
                dd_span['lang'] = dd['lang']
            if 'xml:lang' in dd.attrs:
                dd_span['xml:lang'] = dd['xml:lang']
            if grade < 6:    
                logger.info('Adding <p> elements <dl> elements for grade 1-5')
                p = soup.new_tag('p')
                p.append(dt_span)
                p.append(': ')
                p.append(dd_span)
                dl.insert_before(p)
            else:
                logger.info('Adding <ul> elements <dl> elements for grade 6->')
                li = soup.new_tag('li')
                li.append(dt_span)
                li.append(': ')
                li.append(dd_span)
                ul.append(li)
        if grade >= 6:
            dl.insert_before(ul)
        dl.decompose()

    # ===========================

    # Cleaning comments
    temp_soup = BeautifulSoup(str(soup), "html.parser")
    for comment in temp_soup.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    cleaned_soup = BeautifulSoup(str(temp_soup), "lxml-xml")

    return cleaned_soup

# MAIN
# ====

def main():
    # Parse command line arguments
    parser = ArgumentParser(description='''
        This script prepares the epub file for pandoc conversion to docx format.
        ''')

    parser.add_argument('input',
                        help = 'The input folder')
    parser.add_argument('-o',
                        '--output',
                        help = 'The output epub folder')
    parser.add_argument('-m',
                        '--mathematics',
                        help = 'The epub is a mathematics book',
                        action = 'store_true')
    parser.add_argument('-s',
                        '--science',
                        help = 'The epub is a sience book',
                        action = 'store_true')
    parser.add_argument('-v',
                       '--verbose',
                       help = 'Increase output verbosity',
                       action = 'store_true')
    parser.add_argument('-t',
                        '--toc-levels',
                        help = 'The number of levels in the table of contents',
                        type = int)
    parser.add_argument('-g',
                        '--grade',
                        help = 'The grade level of the book',
                        type = int)
    parser.add_argument('-e',
                        '--excel_creation',
                        help = 'Create Excel files for numeric-heavy tables',
                        action = 'store_true')
    parser.add_argument('-i',
                        '--index',
                        help = 'Do not remove indexes',
                        action = 'store_true')

    args = parser.parse_args()

    # Set up logger
    logger = getLogger(__name__)

    # Set log level
    if args.verbose:
        logger.setLevel(DEBUG)
    else:
        logger.setLevel(INFO)

    # Remove old Excel folder if it exists
    if path.exists(path.join(OUTPUT_DIR, EXCEL_DIR)):
        rmtree(path.join(OUTPUT_DIR, EXCEL_DIR))

    # Check if input folder exists
    if not path.exists(args.input):
        logger.error('Input folder does not exist')
        return

    # Check if input folder is a directory
    if not path.isdir(args.input):
        logger.error('Input folder is not a directory')
        return

    # Find the xhtml file in the input folder
    xhtml = None
    for file in listdir(args.input):
        if file.endswith('.xhtml') and file != 'nav.xhtml':
            xhtml = file
            break

    # Check if xhtml file was found
    if xhtml is None:
        logger.error('No xhtml file found in input folder')
        return

    # Create soup object
    with open(path.join(args.input, xhtml), 'r') as file:
        soup = BeautifulSoup(file, 'xml')

    # Convert epub
    new_soup = prepare(soup, args, logger)
    production_number = xhtml.split('.')[0]

    # Create output folder. Remove old output folder if it exists
    if path.exists(path.join(OUTPUT_DIR, production_number)):
        logger.info('Removing old output folder')
        rmtree(path.join(OUTPUT_DIR, production_number))
    makedirs(path.join(OUTPUT_DIR, production_number))

    # Overwrite the xhtml file in the output folder
    print(f'Writing to {path.join(OUTPUT_DIR, production_number, xhtml)}')
    with open(path.join(OUTPUT_DIR, production_number, xhtml), 'w') as file:
        file.write(str(new_soup))

    # If there is an Excel folder, move it to the output folder of the book
    if path.exists(path.join(OUTPUT_DIR, EXCEL_DIR)):
        copytree(path.join(OUTPUT_DIR, EXCEL_DIR), path.join(OUTPUT_DIR, production_number, EXCEL_DIR))
        rmtree(path.join(OUTPUT_DIR, EXCEL_DIR))

if __name__ == '__main__':
    main()
