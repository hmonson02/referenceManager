# Reference Merger for Biblioshiny

A web-based tool to merge bibliographic references from multiple databases (MEDLINE, Embase, Cochrane CENTRAL), remove duplicates, and export in Scopus format for Biblioshiny/Bibliometrix analysis.

## Features

- **Upload multiple files** - RIS, CSV, TSV formats supported
- **Auto-detect databases** - Recognizes MEDLINE, Embase, Cochrane from filenames
- **Smart deduplication** - Removes duplicates by DOI and title/author/year matching
- **PRISMA summary** - Generates ready-to-use text for your systematic review
- **Year distribution chart** - Visualize publication trends
- **Scopus CSV export** - Works directly with Biblioshiny

## Installation

1. Make sure you have Python 3.8+ installed

2. Install the required packages:
```bash
pip install -r requirements.txt
```

Or install manually:
```bash
pip install streamlit pandas openpyxl
```

## Usage

1. **Start the app:**
```bash
streamlit run reference_merger_app.py
```

2. **Upload your files:**
   - Drag and drop your RIS files from MEDLINE, Embase, Cochrane, etc.
   - Name files with the database name for auto-detection (e.g., `medline_results.ris`)

3. **Process:**
   - Click "Process Files" to merge and deduplicate

4. **Get results:**
   - Copy the PRISMA summary for your paper
   - Download the Scopus CSV file

5. **Import into Biblioshiny:**
   - Open R and run `biblioshiny()`
   - Go to Data tab
   - Select Database: **Scopus**
   - Select Format: **csv**
   - Upload your downloaded file

## File Naming

For automatic database detection, include the database name in your filename:

| Filename | Detected Database |
|----------|------------------|
| `medline_batch1.ris` | MEDLINE |
| `embase_results.ris` | Embase |
| `cochrane_trials.ris` | Cochrane |
| `pubmed_search.ris` | MEDLINE |

Or use the manual mapping option in the sidebar.

## Export Instructions

### MEDLINE/Embase (Ovid)
1. Run search → Select all → Export
2. Format: RIS (Citation Manager)
3. Fields: Complete Reference
4. Export in batches of 500

### Cochrane CENTRAL
1. Run search → Select trials → Export
2. Format: RIS
3. Export in batches of 1000

## Troubleshooting

**App won't start:**
```bash
pip install --upgrade streamlit
```

**File not parsing:**
- Ensure file is UTF-8 encoded
- Try re-exporting from the database

**Biblioshiny import error:**
- Make sure to select "Scopus" as database and "csv" as format
