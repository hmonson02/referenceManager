"""
Reference Merger for Biblioshiny
A web interface to merge bibliographic references from multiple databases,
remove duplicates, and export in Scopus format for Biblioshiny/Bibliometrix.

Run with: streamlit run reference_merger_app.py
"""

import streamlit as st
import pandas as pd
import re
import unicodedata
from pathlib import Path
from collections import Counter
import io

# Page config
st.set_page_config(
    page_title="Reference Merger for Biblioshiny",
    layout="wide"
)

# ============================================================
# HELPER FUNCTIONS
# ============================================================

def normalize_doi(doi):
    """Normalize DOI for comparison and clean URL prefixes."""
    if not doi or pd.isna(doi):
        return ""
    doi = str(doi).strip()
    for prefix in ['https://dx.doi.org/', 'https://doi.org/', 'http://doi.org/', 
                   'http://dx.doi.org/', 'doi:', 'doi.org/']:
        if doi.lower().startswith(prefix.lower()):
            doi = doi[len(prefix):]
    return doi.strip()


def normalize_text(text):
    """Normalize text for comparison."""
    if not text or pd.isna(text):
        return ""
    text = str(text).lower().strip()
    text = unicodedata.normalize('NFD', text)
    text = ''.join(c for c in text if unicodedata.category(c) != 'Mn')
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def create_fingerprint(record):
    """Create a fingerprint for deduplication based on title, authors, and year."""
    title = normalize_text(record.get('title', ''))
    authors = record.get('authors', '') or ''
    first_author = ''
    if authors:
        first_author = str(authors).split(';')[0].split(',')[0].strip().lower()
        first_author = re.sub(r'[^\w]', '', first_author)
    year = str(record.get('year', '') or '')[:4]
    return f"{title[:50]}|{first_author}|{year}"


def detect_source_db(filename):
    """Detect source database from filename."""
    filename_lower = filename.lower()
    if 'embase' in filename_lower:
        return 'Embase'
    elif 'medline' in filename_lower or 'pubmed' in filename_lower:
        return 'MEDLINE'
    elif 'cochrane' in filename_lower or 'central' in filename_lower:
        return 'Cochrane'
    elif 'scopus' in filename_lower:
        return 'Scopus'
    elif 'wos' in filename_lower or 'web of science' in filename_lower or 'savedrecs' in filename_lower:
        return 'Web of Science'
    return 'Unknown'


# ============================================================
# FILE PARSERS
# ============================================================

def parse_ris_content(content, filename=""):
    """Parse RIS format content from various sources (MEDLINE, Embase, Cochrane, Scopus, Web of Science)."""
    records = []
    current_record = {}
    
    # Comprehensive RIS tag mapping supporting multiple database formats
    ris_mapping = {
        # Title
        'TI': 'title', 'T1': 'title',
        # Authors
        'AU': 'authors', 'A1': 'authors', 'A2': 'authors',
        # Year
        'PY': 'year', 'Y1': 'year', 'DA': 'year', 'Y2': 'year',
        # Abstract
        'AB': 'abstract', 'N2': 'abstract',
        # DOI
        'DO': 'doi', 'DOI': 'doi',
        # Journal/Source
        'JF': 'source', 'T2': 'source', 'JO': 'source_abbrev', 'JA': 'source_abbrev', 'J2': 'source_abbrev',
        # Volume, Issue, Pages
        'VL': 'volume', 'IS': 'issue', 'SP': 'page_start', 'EP': 'page_end',
        # ISSN/ISBN
        'SN': 'issn',
        # Publisher
        'PB': 'publisher',
        # Language
        'LA': 'language',
        # Keywords
        'KW': 'keywords',
        # URL
        'UR': 'url', 'L2': 'url',
        # Accession/ID
        'AN': 'accession', 'ID': 'id',
        # Database
        'DB': 'database', 'DP': 'database',
        # Affiliations/Address
        'AD': 'affiliations',
        # Notes
        'N1': 'notes',
        # Document type
        'TY': 'doc_type', 'M3': 'doc_type_alt',
        # PubMed ID
        'PM': 'pmid', 'C2': 'pmid',
        # Article number (Scopus uses C7)
        'C7': 'article_number',
    }
    
    def save_record():
        if current_record:
            if 'AU_list' in current_record:
                current_record['authors'] = ';'.join(current_record.pop('AU_list'))
            if 'KW_list' in current_record:
                current_record['keywords'] = '; '.join(current_record.pop('KW_list'))
            if 'AD_list' in current_record:
                current_record['affiliations'] = '; '.join(current_record.pop('AD_list'))
            records.append(current_record.copy())
    
    lines = content.split('\n')
    for line in lines:
        line = line.rstrip('\r\n')
        match = re.match(r'^([A-Z][A-Z0-9])\s+-\s*(.*)$', line)
        
        if match:
            tag, value = match.groups()
            value = value.strip()
            
            if tag == 'ER':
                save_record()
                current_record = {}
                continue
            
            if tag == 'TY':
                save_record()
                current_record = {'doc_type': value}
                continue
            
            field = ris_mapping.get(tag)
            if field:
                # Handle multiple authors
                if tag in ['AU', 'A1', 'A2']:
                    if 'AU_list' not in current_record:
                        current_record['AU_list'] = []
                    current_record['AU_list'].append(value)
                # Handle multiple keywords
                elif tag == 'KW':
                    if 'KW_list' not in current_record:
                        current_record['KW_list'] = []
                    current_record['KW_list'].append(value)
                # Handle multiple affiliations (Scopus has multiple AD tags)
                elif tag == 'AD':
                    if 'AD_list' not in current_record:
                        current_record['AD_list'] = []
                    current_record['AD_list'].append(value)
                # Handle year - extract 4-digit year
                elif tag in ['PY', 'Y1', 'DA', 'Y2']:
                    year_match = re.search(r'(19|20)\d{2}', value)
                    if year_match:
                        current_record['year'] = year_match.group()
                # Handle ISSN - clean up format
                elif tag == 'SN':
                    # Remove suffixes like "(ISSN)" and take first ISSN if multiple
                    issn_clean = re.sub(r'\s*\(ISSN\)', '', value).strip()
                    if not current_record.get('issn'):
                        current_record['issn'] = issn_clean.split()[0] if issn_clean else ''
                else:
                    # Don't overwrite if already set (first value wins)
                    if field not in current_record:
                        current_record[field] = value
    
    save_record()
    return records


def parse_csv_content(content, filename=""):
    """Parse CSV content."""
    df = pd.read_csv(io.StringIO(content), dtype=str, on_bad_lines='skip')
    
    column_mapping = {
        'title': 'title', 'article title': 'title', 'document title': 'title', 'ti': 'title',
        'authors': 'authors', 'author': 'authors', 'au': 'authors',
        'year': 'year', 'publication year': 'year', 'py': 'year', 'pubyear': 'year',
        'abstract': 'abstract', 'ab': 'abstract',
        'doi': 'doi', 'di': 'doi',
        'journal': 'source', 'source': 'source', 'source title': 'source', 'so': 'source',
        'issn': 'issn', 'sn': 'issn',
        'volume': 'volume', 'vl': 'volume',
        'issue': 'issue', 'is': 'issue',
        'pages': 'pages', 'page': 'pages',
        'keywords': 'keywords', 'author keywords': 'keywords', 'de': 'keywords',
        'language': 'language', 'la': 'language',
        'affiliations': 'affiliations', 'affiliation': 'affiliations',
        'publisher': 'publisher', 'pu': 'publisher',
        'document type': 'doc_type', 'type': 'doc_type', 'dt': 'doc_type',
        'cited by': 'cited_by', 'citations': 'cited_by', 'tc': 'cited_by',
        'url': 'url', 'link': 'url',
        'pmid': 'pmid', 'pubmed id': 'pmid',
    }
    
    df.columns = [col.lower().strip() for col in df.columns]
    rename_dict = {col: column_mapping[col] for col in df.columns if col in column_mapping}
    df = df.rename(columns=rename_dict)
    
    return df.to_dict('records')


def parse_file(uploaded_file):
    """Parse an uploaded file based on its extension."""
    filename = uploaded_file.name
    ext = Path(filename).suffix.lower()
    
    try:
        content = uploaded_file.read().decode('utf-8', errors='replace')
        uploaded_file.seek(0)  # Reset for potential re-read
        
        if ext == '.ris':
            return parse_ris_content(content, filename)
        elif ext == '.csv':
            return parse_csv_content(content, filename)
        elif ext == '.tsv' or ext == '.txt':
            # Try TSV
            df = pd.read_csv(io.StringIO(content), delimiter='\t', dtype=str, on_bad_lines='skip')
            return df.to_dict('records')
        else:
            return []
    except Exception as e:
        st.error(f"Error parsing {filename}: {str(e)}")
        return []


# ============================================================
# DEDUPLICATION
# ============================================================

def deduplicate_records(records):
    """Remove duplicate records based on DOI and title+author+year fingerprint."""
    unique_records = []
    seen_dois = set()
    seen_fingerprints = set()
    
    # Sort by completeness (records with more fields first)
    records_scored = []
    for idx, rec in enumerate(records):
        score = sum(1 for v in rec.values() if v and not pd.isna(v) and str(v).strip())
        if rec.get('doi'): score += 10
        if rec.get('pmid'): score += 5
        if rec.get('abstract'): score += 5
        records_scored.append((score, idx, rec))
    
    records_sorted = [rec for _, _, rec in sorted(records_scored, key=lambda x: (x[0], x[1]), reverse=True)]
    
    duplicates_by_doi = 0
    duplicates_by_fingerprint = 0
    duplicate_details = []  # Track which databases had duplicates
    
    for record in records_sorted:
        is_duplicate = False
        
        # Check by DOI
        doi = normalize_doi(record.get('doi', ''))
        if doi:
            if doi.lower() in seen_dois:
                is_duplicate = True
                duplicates_by_doi += 1
                duplicate_details.append(('DOI', record.get('_source_db', 'Unknown')))
            else:
                seen_dois.add(doi.lower())
        
        # Check by fingerprint
        if not is_duplicate:
            fingerprint = create_fingerprint(record)
            if fingerprint and len(fingerprint) > 10:
                if fingerprint in seen_fingerprints:
                    is_duplicate = True
                    duplicates_by_fingerprint += 1
                    duplicate_details.append(('Fingerprint', record.get('_source_db', 'Unknown')))
                else:
                    seen_fingerprints.add(fingerprint)
        
        if not is_duplicate:
            unique_records.append(record)
    
    return unique_records, duplicates_by_doi, duplicates_by_fingerprint, duplicate_details


# ============================================================
# CONVERT TO SCOPUS FORMAT
# ============================================================

def convert_to_scopus_format(records):
    """Convert records to Scopus CSV format for Biblioshiny import."""
    scopus_records = []
    
    for i, rec in enumerate(records):
        authors = rec.get('authors', '') or ''
        title = rec.get('title', '') or ''
        year = rec.get('year', '') or ''
        source = rec.get('source', '') or ''
        volume = rec.get('volume', '') or ''
        issue = rec.get('issue', '') or ''
        doi = normalize_doi(rec.get('doi', '') or '')
        abstract = rec.get('abstract', '') or ''
        keywords = rec.get('keywords', '') or ''
        affiliations = rec.get('affiliations', '') or ''
        publisher = rec.get('publisher', '') or ''
        issn = rec.get('issn', '') or ''
        pmid = rec.get('pmid', '') or ''
        language = rec.get('language', 'English') or 'English'
        source_abbrev = rec.get('source_abbrev', '') or ''
        url = rec.get('url', '') or ''
        
        page_start = rec.get('page_start', '') or ''
        page_end = rec.get('page_end', '') or ''
        
        # Parse pages if not already split
        pages = rec.get('pages', '') or ''
        if pages and not page_start:
            if '-' in str(pages):
                parts = str(pages).split('-')
                page_start = parts[0].strip()
                page_end = parts[-1].strip() if len(parts) > 1 else ''
            else:
                page_start = str(pages)
        
        # Extract year as integer
        year_int = ''
        if year:
            year_match = re.search(r'(19|20)\d{2}', str(year))
            if year_match:
                year_int = year_match.group()
        
        scopus_rec = {
            'Authors': authors,
            'Author full names': authors,
            'Author(s) ID': '',
            'Title': title,
            'Year': year_int,
            'Source title': source,
            'Volume': volume,
            'Issue': issue,
            'Art. No.': '',
            'Page start': page_start,
            'Page end': page_end,
            'Cited by': '0',
            'DOI': doi,
            'Link': url,
            'Affiliations': affiliations,
            'Authors with affiliations': '',
            'Abstract': abstract,
            'Author Keywords': keywords,
            'Index Keywords': '',
            'Molecular Sequence Numbers': '',
            'Chemicals/CAS': '',
            'Tradenames': '',
            'Manufacturers': '',
            'Funding Details': '',
            'Funding Texts': '',
            'References': '',
            'Correspondence Address': '',
            'Editors': '',
            'Publisher': publisher,
            'Sponsors': '',
            'Conference name': '',
            'Conference date': '',
            'Conference location': '',
            'Conference code': '',
            'ISSN': issn,
            'ISBN': '',
            'CODEN': '',
            'PubMed ID': pmid,
            'Language of Original Document': language,
            'Abbreviated Source Title': source_abbrev,
            'Document Type': 'Article',
            'Publication Stage': 'Final',
            'Open Access': '',
            'Source': 'Scopus',
            'EID': f'2-s2.0-{85000000000 + i}',
        }
        
        scopus_records.append(scopus_rec)
    
    df = pd.DataFrame(scopus_records)
    
    column_order = [
        'Authors', 'Author full names', 'Author(s) ID', 'Title', 'Year', 'Source title',
        'Volume', 'Issue', 'Art. No.', 'Page start', 'Page end', 'Cited by', 'DOI', 'Link',
        'Affiliations', 'Authors with affiliations', 'Abstract', 'Author Keywords',
        'Index Keywords', 'Molecular Sequence Numbers', 'Chemicals/CAS', 'Tradenames',
        'Manufacturers', 'Funding Details', 'Funding Texts', 'References',
        'Correspondence Address', 'Editors', 'Publisher', 'Sponsors', 'Conference name',
        'Conference date', 'Conference location', 'Conference code', 'ISSN', 'ISBN',
        'CODEN', 'PubMed ID', 'Language of Original Document', 'Abbreviated Source Title',
        'Document Type', 'Publication Stage', 'Open Access', 'Source', 'EID'
    ]
    
    df = df[column_order]
    return df


# ============================================================
# MAIN APP
# ============================================================

def main():
    st.title("Reference Merger for Biblioshiny")
    st.markdown("""
    Upload bibliographic exports from **MEDLINE**, **Embase**, **Cochrane CENTRAL**, or other databases.
    This tool will merge them, remove duplicates, and create a **Scopus-format CSV** for Biblioshiny.
    """)
    
    # Sidebar for database mapping
    st.sidebar.header("Settings")
    st.sidebar.markdown("**Database Detection**")
    st.sidebar.markdown("""
    Files are auto-detected based on filename:
    - `medline_*.ris` - MEDLINE
    - `embase_*.ris` - Embase  
    - `cochrane_*.ris` - Cochrane
    - `scopus_*.ris` - Scopus
    - `savedrecs_*.ris or Web of Science_*.ris or wos_*.ris in filename` - Web of Science
    
    Or use manual mapping below.
    """)
    
    # Manual database mapping
    use_manual_mapping = st.sidebar.checkbox("Use manual database mapping")
    manual_mappings = {}
    
    # File upload
    st.header("1. Upload Files")
    uploaded_files = st.file_uploader(
        "Upload your RIS, CSV, or TSV files",
        type=['ris', 'csv', 'tsv', 'txt'],
        accept_multiple_files=True,
        help="You can upload multiple files from different databases"
    )
    
    if uploaded_files:
        st.success(f"{len(uploaded_files)} file(s) uploaded")
        
        # Show file list and allow manual database selection
        if use_manual_mapping:
            st.subheader("Assign databases to files:")
            cols = st.columns(2)
            for i, f in enumerate(uploaded_files):
                with cols[i % 2]:
                    db = st.selectbox(
                        f"{f.name}",
                        options=['Auto-detect', 'MEDLINE', 'Embase', 'Cochrane', 'Scopus', 'Web of Science', 'Other'],
                        key=f"db_{f.name}"
                    )
                    if db != 'Auto-detect':
                        manual_mappings[f.name] = db
        
        # Process button
        if st.button("Process Files", type="primary"):
            with st.spinner("Processing files..."):
                all_records = []
                records_per_source = {}
                file_record_counts = {}
                
                progress_bar = st.progress(0)
                
                for i, uploaded_file in enumerate(uploaded_files):
                    filename = uploaded_file.name
                    
                    # Determine source database
                    if filename in manual_mappings:
                        source_db = manual_mappings[filename]
                    else:
                        source_db = detect_source_db(filename)
                    
                    # Parse file
                    records = parse_file(uploaded_file)
                    
                    # Add source database to each record
                    for rec in records:
                        rec['_source_db'] = source_db
                    
                    # Track counts
                    file_record_counts[filename] = len(records)
                    records_per_source[source_db] = records_per_source.get(source_db, 0) + len(records)
                    all_records.extend(records)
                    
                    progress_bar.progress((i + 1) / len(uploaded_files))
                
                # Deduplicate
                unique_records, dup_doi, dup_fp, dup_details = deduplicate_records(all_records)
                total_duplicates = dup_doi + dup_fp
                
                # Convert to Scopus format
                scopus_df = convert_to_scopus_format(unique_records)
                
                # Store results in session state
                st.session_state['results'] = {
                    'total_parsed': len(all_records),
                    'unique_records': len(unique_records),
                    'duplicates_doi': dup_doi,
                    'duplicates_fingerprint': dup_fp,
                    'total_duplicates': total_duplicates,
                    'records_per_source': records_per_source,
                    'file_record_counts': file_record_counts,
                    'scopus_df': scopus_df,
                    'unique_records_list': unique_records,
                }
                
                st.success("Processing complete!")
    
    # Display results if available
    if 'results' in st.session_state:
        results = st.session_state['results']
        
        st.header("2. PRISMA Flow Diagram Data")
        
        # PRISMA-style table
        col1, col2 = st.columns(2)
        
        with col1:
            st.subheader("Identification")
            
            # Records per database
            prisma_data = []
            for db, count in sorted(results['records_per_source'].items(), key=lambda x: -x[1]):
                prisma_data.append({
                    'Database': db,
                    'Records': count
                })
            
            prisma_df = pd.DataFrame(prisma_data)
            st.dataframe(prisma_df, use_container_width=True, hide_index=True)
            
            st.metric("Total Records Identified", results['total_parsed'])
        
        with col2:
            st.subheader("Screening")
            
            st.metric("Duplicate Records Removed", results['total_duplicates'])
            
            dup_breakdown = pd.DataFrame([
                {'Method': 'By DOI', 'Count': results['duplicates_doi']},
                {'Method': 'By Title/Author/Year', 'Count': results['duplicates_fingerprint']},
            ])
            st.dataframe(dup_breakdown, use_container_width=True, hide_index=True)
            
            st.metric("Records After Deduplication", results['unique_records'], 
                     delta=f"-{results['total_duplicates']} duplicates")
        
        # PRISMA summary box
        st.subheader("PRISMA Summary (Copy for your paper)")
        
        db_strings = [f"{db} (n = {count})" for db, count in sorted(results['records_per_source'].items(), key=lambda x: -x[1])]
        prisma_text = f"""**Identification:**
Records identified through database searching:
{chr(10).join('• ' + s for s in db_strings)}
Total: n = {results['total_parsed']}

**Screening:**
Duplicate records removed: n = {results['total_duplicates']}
• By DOI matching: n = {results['duplicates_doi']}
• By title/author/year: n = {results['duplicates_fingerprint']}

**Included:**
Records after deduplication: n = {results['unique_records']}"""
        
        st.text_area("PRISMA Text", prisma_text, height=250)
        
        # Year distribution
        st.subheader("Publication Year Distribution")
        years = [r.get('year', '') for r in results['unique_records_list']]
        year_ints = []
        for y in years:
            if y:
                match = re.search(r'(19|20)\d{2}', str(y))
                if match:
                    year_ints.append(int(match.group()))
        
        if year_ints:
            year_counts = Counter(year_ints)
            year_df = pd.DataFrame([
                {'Year': y, 'Count': c} for y, c in sorted(year_counts.items())
            ])
            st.bar_chart(year_df.set_index('Year'))
            
            col1, col2, col3 = st.columns(3)
            col1.metric("Earliest Year", min(year_ints))
            col2.metric("Latest Year", max(year_ints))
            col3.metric("Most Common Year", max(year_counts, key=year_counts.get))
        
        # Download section
        st.header("3. Download Output")
        
        st.markdown("""
        **Import into Biblioshiny:**
        1. Open Biblioshiny: `biblioshiny()`
        2. Go to **Data** tab
        3. Select Database: **Scopus**
        4. Select Format: **csv**
        5. Upload the downloaded file
        """)
        
        # Convert DataFrame to CSV
        csv_buffer = io.StringIO()
        results['scopus_df'].to_csv(csv_buffer, index=False)
        csv_data = csv_buffer.getvalue()
        
        st.download_button(
            label="Download Scopus CSV",
            data=csv_data,
            file_name="merged_references_scopus.csv",
            mime="text/csv",
            type="primary"
        )
        
        # Preview
        with st.expander("Preview Output Data"):
            st.dataframe(
                results['scopus_df'][['Authors', 'Title', 'Year', 'Source title', 'DOI']].head(20),
                use_container_width=True
            )


if __name__ == "__main__":
    main()
