import streamlit as st
import pandas as pd
import numpy as np
import requests
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote
import re
from collections import Counter, defaultdict
import json
from datetime import datetime, timedelta
import io
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import base64
import os
import random
import seaborn as sns
import matplotlib.pyplot as plt
from typing import List, Tuple

# Import translation manager
from languages import translation_manager

# --- Page Configuration ---
st.set_page_config(
    page_title="Advanced Journal Analysis Tool",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- Global Settings ---
EMAIL = st.secrets.get("EMAIL", "your.email@example.com") if hasattr(st, 'secrets') else "your.email@example.com"
MAX_WORKERS = 5
RETRIES = 3
DELAYS = [0.2, 0.5, 0.7, 1.0, 1.3, 1.5, 2.0]

# --- State Storage Classes ---
class AnalysisState:
    def __init__(self):
        self.crossref_cache = {}
        self.openalex_cache = {}
        self.unified_cache = {}
        self.citing_cache = defaultdict(list)
        self.institution_cache = {}
        self.journal_cache = {}
        self.analysis_results = None
        self.current_progress = 0
        self.progress_text = ""
        self.analysis_complete = False
        self.excel_buffer = None
        self.if_data = None
        self.cs_data = None

# --- Terms Dictionary ---
class JournalAnalysisGlossary:
    def __init__(self):
        self.terms = {
            'H-index': {
                'definition': translation_manager.get_text('h_index_tooltip'),
                'calculation': 'Articles are sorted in descending order of citations, the maximum number h is found where the h-th article has at least h citations',
                'interpretation': 'Higher = better. Shows both productivity and influence of author/journal',
                'category': 'Citations',
                'example': 'H-index 10 means that a scientist/journal has 10 articles, each of which has been cited at least 10 times'
            },
            'Reference Age': {
                'definition': 'Average age of references in journal articles (median value)',
                'calculation': 'Difference between article publication year and publication years of cited works',
                'interpretation': 'Low age = journal cites contemporary works. High age = reliance on classical works',
                'category': 'References',
                'example': 'Reference Age 8 years means that half of references in articles are younger than 8 years, half are older'
            },
            'JSCR': {
                'definition': 'Journal Self-Citation Rate - percentage of journal self-citations',
                'calculation': '(Number of citations to articles of this same journal / Total number of citations) × 100%',
                'interpretation': 'Normal: 10-20%. Above 30% may indicate isolation. Below 5% - wide citability',
                'category': 'Citations',
                'example': 'JSCR 15% means that 15% of all journal citations are to its own articles'
            },
            'Cited Half-Life': {
                'definition': 'Citation half-life - time during which an article receives half of all its citations',
                'calculation': 'Years from publication to moment when 50% of total citations are accumulated',
                'interpretation': 'Short half-life = quick return (technical sciences). Long = long-term influence (fundamental sciences)',
                'category': 'Citations',
                'example': 'Cited Half-Life 4 years means that in the first 4 years the article receives half of all its citations'
            },
            'FWCI': {
                'definition': 'Field-Weighted Citation Impact - field-weighted citation index',
                'calculation': 'Actual citations / Expected citations for this field',
                'interpretation': '1.0 = average level. >1.2 = above average. >1.5 = significantly above average',
                'category': 'Citations',
                'example': 'FWCI 1.8 means that articles are cited 80% more often than average in their field'
            },
            'Citation Velocity': {
                'definition': 'Citation velocity - average number of citations per year for first 2 years after publication',
                'calculation': 'Number of citations in first 2 years / 2',
                'interpretation': 'Higher = faster recognition by scientific community. Depends on discipline',
                'category': 'Citations',
                'example': 'Velocity 3.5 means that on average an article receives 3.5 citations per year in first two years'
            },
            'OA Impact Premium': {
                'definition': 'Open Access premium - difference in citations between OA and non-OA articles',
                'calculation': '((Average OA citations - Average non-OA citations) / Average non-OA citations) × 100%',
                'interpretation': 'Positive premium = OA articles are cited more frequently. Usually +10% to +50%',
                'category': 'Citations',
                'example': 'OA Premium 25% means that open access articles are cited 25% more frequently'
            },
            'Elite Index': {
                'definition': 'Percentage of journal articles in top-10% most cited works in their field',
                'calculation': 'Number of articles in top-10% by citations / Total number of articles × 100%',
                'interpretation': 'Higher = more high-performance articles. Excellent indicator >20%',
                'category': 'Citations',
                'example': 'Elite Index 15% means that 15% of journal articles are in 10% most cited in their field'
            },
            'Author Gini': {
                'definition': 'Gini index for authors - measure of inequality in publication distribution among authors',
                'calculation': 'Statistical indicator from 0 to 1, where 0 = complete equality, 1 = maximum inequality',
                'interpretation': 'Low (0.1-0.3) = uniform distribution. High (0.6+) = few authors dominate',
                'category': 'Authors',
                'example': 'Gini 0.4 means moderate inequality - some authors publish significantly more frequently than others'
            },
            'DBI': {
                'definition': 'Diversity Balance Index - thematic diversification index',
                'calculation': 'Normalized Shannon index by thematic concepts of articles',
                'interpretation': '0-1, where 0 = one theme, 1 = uniform distribution across many themes',
                'category': 'Themes',
                'example': 'DBI 0.7 means good diversification across several thematic directions'
            },
            'Self-Cites': {
                'definition': 'Self-citations - references to other articles of the same journal in bibliography',
                'calculation': 'Number of references with DOI prefix of this journal',
                'interpretation': 'Moderate self-citations are normal. Excessive may artificially inflate metrics',
                'category': 'References',
                'example': '15 self-citations out of 100 references = 15% self-citations'
            },
            'International Collaboration': {
                'definition': 'International collaboration - percentage of articles with authors from different countries',
                'calculation': 'Articles with authors from ≥2 countries / All articles × 100%',
                'interpretation': 'Higher = more international journal. Indicator of research globalization',
                'category': 'Authors',
                'example': '60% international articles means that in most works authors from different countries participate'
            },
            'ISSN': {
                'definition': 'International Standard Serial Number - unique identifier for serial publications',
                'calculation': '8-digit code format XXXX-XXXX, assigned to journals',
                'interpretation': 'Used for unambiguous journal identification in international databases',
                'category': 'Journal',
                'example': 'ISSN 2411-1414 identifies journal Chimica Techno Acta'
            },
            'DOI': {
                'definition': 'Digital Object Identifier - permanent link to digital object',
                'calculation': 'Unique identifier format 10.XXXX/XXXXX for scientific articles',
                'interpretation': 'Provides permanent availability and citability of scientific works',
                'category': 'Technical',
                'example': 'DOI 10.15826/chimtech.2024.11.1.01 unambiguously identifies specific article'
            },
            'Crossref': {
                'definition': 'System of mutual references between scientific publications',
                'calculation': 'Database of references between articles with metadata',
                'interpretation': 'Main source of citation data and article metadata',
                'category': 'Databases',
                'example': 'Crossref contains information about 140+ million scientific works'
            },
            'OpenAlex': {
                'definition': 'Open database of scientific publications, authors and institutions',
                'calculation': 'Alternative to Scopus/WoS with open access to data',
                'interpretation': 'Provides extended metrics and connections between scientific objects',
                'category': 'Databases',
                'example': 'OpenAlex contains data about 200+ million scientific works'
            }
        }
        
        self.category_colors = {
            'Citations': '🔵',
            'References': '🟢',
            'Authors': '🟠',
            'Themes': '🟣',
            'Journal': '🔴',
            'Technical': '⚫',
            'Databases': '🟤'
        }
    
    def get_tooltip(self, term):
        """Generate text for tooltip"""
        if term not in self.terms:
            return f"Term '{term}' not found in dictionary"
        
        info = self.terms[term]
        tooltip = f"**{term}**\n\n{info['definition']}"
        
        if 'calculation' in info:
            tooltip += f"\n\n**Calculation:** {info['calculation']}"
        if 'interpretation' in info:
            tooltip += f"\n\n**Interpretation:** {info['interpretation']}"
            
        return tooltip
    
    def get_detailed_info(self, term):
        """Complete term information for extended tooltips"""
        if term not in self.terms:
            return None
        
        info = self.terms[term]
        category_icon = self.category_colors.get(info['category'], '⚪')
        
        detailed = {
            'term': term,
            'definition': info['definition'],
            'calculation': info.get('calculation', 'Not specified'),
            'interpretation': info.get('interpretation', 'Not specified'),
            'category': f"{category_icon} {info['category']}",
            'example': info.get('example', 'Example not provided')
        }
        
        return detailed
    
    def get_terms_by_category(self, category):
        """Get all terms of category"""
        return [term for term, info in self.terms.items() if info['category'] == category]
    
    def get_random_term(self):
        """Random term for learning"""
        return random.choice(list(self.terms.keys()))

# Initialize global dictionary
glossary = JournalAnalysisGlossary()

# --- State Initialization ---
def initialize_analysis_state():
    if 'analysis_state' not in st.session_state:
        st.session_state.analysis_state = AnalysisState()
    
    # Initialize learned terms
    if 'learned_terms' not in st.session_state:
        st.session_state.learned_terms = set()
    
    # Initialize viewed terms in this session
    if 'viewed_terms' not in st.session_state:
        st.session_state.viewed_terms = set()

def get_analysis_state():
    return st.session_state.analysis_state

# --- Rate Limiter ---
class RateLimiter:
    def __init__(self, calls_per_second=5):
        self.calls_per_second = calls_per_second
        self.timestamps = []
        self.lock = threading.Lock()
    
    def wait_if_needed(self):
        with self.lock:
            now = time.time()
            self.timestamps = [ts for ts in self.timestamps if now - ts < 1.0]
            
            if len(self.timestamps) >= self.calls_per_second:
                sleep_time = 1.0 - (now - self.timestamps[0])
                if sleep_time > 0:
                    time.sleep(sleep_time)
                self.timestamps = self.timestamps[1:]
            
            self.timestamps.append(now)

rate_limiter = RateLimiter(calls_per_second=8)

# --- Adaptive Delay ---
class AdaptiveDelayer:
    def __init__(self):
        self.lock = threading.Lock()
        self.delay_index = 0

    def wait(self, success=True):
        with self.lock:
            if success:
                self.delay_index = 0
            else:
                self.delay_index = min(self.delay_index + 1, len(DELAYS) - 1)
            delay = DELAYS[self.delay_index]
            time.sleep(delay)
            return delay

delayer = AdaptiveDelayer()

# --- Configuration ---
class JournalAnalyzerConfig:
    def __init__(self):
        self.email = EMAIL
        self.max_workers = MAX_WORKERS
        self.retries = RETRIES
        self.delays = DELAYS
        self.timeouts = {
            'crossref': 15,
            'openalex': 10,
            'batch': 30
        }
        self.batch_sizes = {
            'metadata': 10,
            'citations': 5
        }

config = JournalAnalyzerConfig()

# --- Helper Functions ---
def update_progress(progress, text):
    state = get_analysis_state()
    state.current_progress = progress
    state.progress_text = text

# --- Period Validation and Parsing ---
def parse_period(period_str):
    years = set()
    parts = [p.strip() for p in period_str.replace(' ', '').split(',') if p.strip()]
    for part in parts:
        if '-' in part:
            try:
                s, e = map(int, part.split('-'))
                if 1900 <= s <= 2100 and 1900 <= e <= 2100 and s <= e:
                    years.update(range(s, e + 1))
                else:
                    st.warning(translation_manager.get_text('range_out_of_bounds').format(part=part))
            except ValueError:
                st.warning(translation_manager.get_text('range_parsing_error').format(part=part))
        else:
            try:
                y = int(part)
                if 1900 <= y <= 2100:
                    years.add(y)
                else:
                    st.warning(translation_manager.get_text('year_out_of_bounds').format(year=y))
            except ValueError:
                st.warning(translation_manager.get_text('not_a_year').format(part=part))
    if not years:
        st.error(translation_manager.get_text('no_correct_years'))
        return []
    return sorted(years)

# --- Data Validation ---
def validate_and_clean_data(items):
    validated = []
    skipped_count = 0
    
    for item in items:
        if not item.get('DOI'):
            skipped_count += 1
            continue
            
        doi = item['DOI'].lower().strip()
        if not doi.startswith('10.'):
            skipped_count += 1
            continue
            
        date_parts = item.get('created', {}).get('date-parts', [[]])[0]
        if not date_parts or date_parts[0] < 1900:
            skipped_count += 1
            continue
            
        item['DOI'] = doi
        validated.append(item)
    
    if skipped_count > 0:
        st.warning(translation_manager.get_text('articles_skipped').format(count=skipped_count))
    return validated

# === 1. Journal Name ===
def get_journal_name(issn):
    state = get_analysis_state()
    if issn in state.crossref_cache.get('journals', {}):
        return state.crossref_cache['journals'][issn]
    url = f"https://api.openalex.org/sources?filter=issn:{issn}"
    for _ in range(RETRIES):
        try:
            rate_limiter.wait_if_needed()
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                if data['meta']['count'] > 0:
                    name = data['results'][0]['display_name']
                    if 'journals' not in state.crossref_cache:
                        state.crossref_cache['journals'] = {}
                    state.crossref_cache['journals'][issn] = name
                    delayer.wait(success=True)
                    return name
        except:
            pass
        delayer.wait(success=False)
    return translation_manager.get_text('journal_not_found')

# === 2. Crossref Metadata Retrieval ===
def get_crossref_metadata(doi, state):
    if doi in state.crossref_cache:
        return state.crossref_cache[doi]
    if not doi or doi == 'N/A':
        return None
    url = f"https://api.crossref.org/works/{quote(doi)}"
    headers = {'User-Agent': f"YourApp/1.0 (mailto:{EMAIL})"}
    for _ in range(RETRIES):
        try:
            rate_limiter.wait_if_needed()
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code == 200:
                data = resp.json()['message']
                state.crossref_cache[doi] = data
                delayer.wait(success=True)
                return data
        except:
            pass
        delayer.wait(success=False)
    return None

# === 3. OpenAlex Metadata Retrieval ===
def get_openalex_metadata(doi, state):
    if doi in state.openalex_cache:
        return state.openalex_cache[doi]
    if not doi or doi == 'N/A':
        return None
    normalized = doi if doi.startswith('http') else f"https://doi.org/{doi}"
    url = f"https://api.openalex.org/works/{quote(normalized)}"
    for _ in range(RETRIES):
        try:
            rate_limiter.wait_if_needed()
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                state.openalex_cache[doi] = data
                delayer.wait(success=True)
                return data
        except:
            pass
        delayer.wait(success=False)
    return None

# === 4. Unified Metadata ===
def get_unified_metadata(args):
    doi, state = args
    if doi in state.unified_cache:
        return state.unified_cache[doi]
    
    if not doi or doi == 'N/A':
        return {'crossref': None, 'openalex': None}
    
    cr_data = get_crossref_metadata(doi, state)
    oa_data = get_openalex_metadata(doi, state)
    
    result = {'crossref': cr_data, 'openalex': oa_data}
    state.unified_cache[doi] = result
    return result

# === 5. Citing DOI Retrieval and Their Metadata ===
def get_citing_dois_and_metadata(args):
    analyzed_doi, state = args
    if analyzed_doi in state.citing_cache:
        return state.citing_cache[analyzed_doi]
    citing_list = []
    oa_data = get_openalex_metadata(analyzed_doi, state)
    if not oa_data or oa_data.get('cited_by_count', 0) == 0:
        state.citing_cache[analyzed_doi] = citing_list
        return citing_list
    work_id = oa_data['id'].split('/')[-1]
    url = f"https://api.openalex.org/works?filter=cites:{work_id}&per-page=100"
    cursor = "*"
    
    while cursor:
        success = False
        for _ in range(RETRIES):
            try:
                rate_limiter.wait_if_needed()
                resp = requests.get(f"{url}&cursor={cursor}", timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    new_items = data.get('results', [])  # Определяем new_items здесь
                    for w in new_items:
                        c_doi = w.get('doi')
                        if c_doi:
                            if c_doi not in state.crossref_cache:
                                get_crossref_metadata(c_doi, state)
                            if c_doi not in state.openalex_cache:
                                get_openalex_metadata(c_doi, state)
                            citing_list.append({
                                'doi': c_doi,
                                'pub_date': w.get('publication_date'),
                                'crossref': state.crossref_cache.get(c_doi),
                                'openalex': state.openalex_cache.get(c_doi)
                            })
                    cursor = data['meta'].get('next_cursor')
                    delayer.wait(success=True)
                    success = True
                    break
            except:
                pass
            delayer.wait(success=False)
        if not success:
            break
        if not new_items:  # Теперь new_items определена
            break
    state.citing_cache[analyzed_doi] = citing_list
    return citing_list

# === 6. Affiliation and Country Extraction ===
def extract_affiliations_and_countries(openalex_data):
    affiliations = set()
    countries = set()
    authors_list = []
    
    if not openalex_data:
        return authors_list, list(affiliations), list(countries)
    
    # Check for 'authorships' key
    if 'authorships' not in openalex_data:
        return authors_list, list(affiliations), list(countries)
    
    try:
        for auth in openalex_data['authorships']:
            author_name = auth.get('author', {}).get('display_name', 'Unknown')
            authors_list.append(author_name)
            
            # Check for 'institutions' key
            if 'institutions' in auth:
                for inst in auth.get('institutions', []):
                    inst_name = inst.get('display_name')
                    country_code = inst.get('country_code')
                    
                    if inst_name:
                        affiliations.add(inst_name)
                    if country_code:
                        countries.add(country_code.upper())
    except (KeyError, TypeError, AttributeError) as e:
        # Log error but continue execution
        print(f"Warning in extract_affiliations_and_countries: {e}")
        pass
    
    return authors_list, list(affiliations), list(countries)

# === 7. Journal Information Extraction ===
def extract_journal_info(metadata):
    journal_info = {
        'issn': [],
        'journal_name': '',
        'publisher': ''
    }
    
    if not metadata:
        return journal_info
    
    cr = metadata.get('crossref')
    if cr:
        journal_info['issn'] = cr.get('ISSN', [])
        journal_info['journal_name'] = cr.get('container-title', [''])[0] if cr.get('container-title') else ''
        journal_info['publisher'] = cr.get('publisher', '')
    
    oa = metadata.get('openalex')
    if oa:
        host_venue = oa.get('host_venue', {})
        if host_venue:
            if not journal_info['journal_name']:
                journal_info['journal_name'] = host_venue.get('display_name', '')
            if not journal_info['publisher']:
                journal_info['publisher'] = host_venue.get('publisher', '')
            if not journal_info['issn']:
                journal_info['issn'] = host_venue.get('issn', [])
    
    return journal_info

# === 8. Article Retrieval from Crossref ===
def fetch_articles_by_issn_period(issn, from_date, until_date):
    base_url = "https://api.crossref.org/works"
    items = []
    cursor = "*"
    params = {
        'filter': f'issn:{issn},from-pub-date:{from_date},until-pub-date:{until_date}',
        'rows': 1000,
        'cursor': cursor,
        'mailto': EMAIL
    }
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    progress_container = st.container()
    
    with progress_container:
        st.info("📥 " + translation_manager.get_text('loading_articles') + " **Crossref** " + translation_manager.get_text('and') + " **OpenAlex**. " + translation_manager.get_text('analysis_may_take_time') + " " + translation_manager.get_text('reduce_period_recommended'))
    
    while cursor:
        params['cursor'] = cursor
        success = False
        new_items = []  # Определяем new_items здесь
        for _ in range(RETRIES):
            try:
                rate_limiter.wait_if_needed()
                resp = requests.get(base_url, params=params, timeout=15)
                if resp.status_code == 200:
                    data = resp.json()
                    new_items = data['message']['items']  # Присваиваем значение
                    items.extend(new_items)
                    cursor = data['message'].get('next-cursor')
                    
                    status_text.text(f"📥 {translation_manager.get_text('loaded_articles').format(count=len(items))}")
                    if cursor:
                        progress = min(len(items) / (len(items) + 100), 0.95)
                        progress_bar.progress(progress)
                    
                    delayer.wait(success=True)
                    success = True
                    break
            except Exception as e:
                st.error(translation_manager.get_text('loading_error').format(error=e))
            delayer.wait(success=False)
        if not success:
            break
        if not new_items:  # Теперь new_items определена
            break
    
    progress_bar.progress(1.0)
    status_text.text(f"✅ {translation_manager.get_text('articles_loaded').format(count=len(items))}")
    time.sleep(0.5)
    progress_bar.empty()
    status_text.empty()
    progress_container.empty()
    
    return items

# === 9. DOI Prefix Extraction ===
def get_doi_prefix(doi):
    if not doi or doi == 'N/A':
        return ''
    return doi.split('/')[0] if '/' in doi else doi[:7]

# === 10. Processing with Progress Bar ===
def process_with_progress(items, func, desc="Processing", unit="items"):
    results = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {executor.submit(func, item): item for item in items}
        
        for i, future in enumerate(as_completed(futures)):
            try:
                results.append(future.result())
            except Exception as e:
                st.error(f"Error in {desc}: {e}")
                results.append(None)
            
            progress = (i + 1) / len(items)
            progress_bar.progress(progress)
            status_text.text(f"{desc}: {i + 1}/{len(items)}")
    
    progress_bar.empty()
    status_text.empty()
    return results

# === 11. Analysis of Overlaps Between Analyzed and Citing Works ===
def analyze_overlaps(analyzed_metadata, citing_metadata, state):
    """Analysis of overlaps between analyzed and citing works"""
    
    overlap_details = []
    
    for analyzed in analyzed_metadata:
        if not analyzed or not analyzed.get('crossref'):
            continue
            
        analyzed_doi = analyzed['crossref'].get('DOI')
        if not analyzed_doi:
            continue
            
        # Get authors and affiliations of analyzed work
        analyzed_authors, analyzed_affiliations, _ = extract_affiliations_and_countries(analyzed.get('openalex'))
        analyzed_authors_set = set(analyzed_authors)
        analyzed_affiliations_set = set(analyzed_affiliations)
        
        # Get citing works
        citings = get_citing_dois_and_metadata((analyzed_doi, state))
        
        for citing in citings:
            if not citing or not citing.get('openalex'):
                continue
                
            citing_doi = citing.get('doi')
            if not citing_doi:
                continue
            
            # Get authors and affiliations of citing work
            citing_authors, citing_affiliations, _ = extract_affiliations_and_countries(citing.get('openalex'))
            citing_authors_set = set(citing_authors)
            citing_affiliations_set = set(citing_affiliations)
            
            # Find overlaps
            common_authors = analyzed_authors_set.intersection(citing_authors_set)
            common_affiliations = analyzed_affiliations_set.intersection(citing_affiliations_set)
            
            if common_authors or common_affiliations:
                overlap_details.append({
                    'analyzed_doi': analyzed_doi,
                    'citing_doi': citing_doi,
                    'common_authors': list(common_authors),
                    'common_affiliations': list(common_affiliations),
                    'common_authors_count': len(common_authors),
                    'common_affiliations_count': len(common_affiliations)
                })
    
    return overlap_details

# === 12. Citation Accumulation Speed Analysis ===
def analyze_citation_accumulation(analyzed_metadata, state):
    accumulation_data = defaultdict(lambda: defaultdict(int))
    yearly_citations = defaultdict(int)
    
    for analyzed in analyzed_metadata:
        if analyzed and analyzed.get('crossref'):
            analyzed_doi = analyzed['crossref'].get('DOI')
            if not analyzed_doi:
                continue
                
            pub_year = analyzed['crossref'].get('published', {}).get('date-parts', [[0]])[0][0]
            if not pub_year:
                continue
            
            citings = get_citing_dois_and_metadata((analyzed_doi, state))
            
            for citing in citings:
                if citing.get('openalex'):
                    cite_year = citing['openalex'].get('publication_year', 0)
                    if cite_year >= pub_year:
                        yearly_citations[cite_year] += 1
                        years_since_pub = cite_year - pub_year
                        if years_since_pub >= 0:
                            for year in range(years_since_pub + 1):
                                accumulation_data[pub_year][year] += 1
    
    accumulation_curves = {}
    for pub_year, yearly_counts in accumulation_data.items():
        sorted_years = sorted(yearly_counts.keys())
        cumulative_counts = []
        current_total = 0
        for year in sorted_years:
            current_total += yearly_counts[year]
            cumulative_counts.append({
                'years_since_publication': year,
                'cumulative_citations': current_total
            })
        accumulation_curves[pub_year] = cumulative_counts
    
    yearly_stats = []
    for year in sorted(yearly_citations.keys()):
        yearly_stats.append({
            'year': year,
            'citations_count': yearly_citations[year]
        })
    
    return {
        'accumulation_curves': dict(accumulation_curves),
        'yearly_citations': yearly_stats,
        'total_years_covered': len(yearly_citations)
    }

# === 13. Metadata Processing for Statistics ===
def extract_stats_from_metadata(metadata_list, is_analyzed=True, journal_prefix=''):
    total_refs = 0
    refs_with_doi = 0
    refs_without_doi = 0
    self_cites = 0
    ref_counts = []
    author_counts = []
    single_authors = 0
    multi_authors_gt10 = 0
    author_freq = Counter()
    pub_dates = []
    
    articles_with_10_citations = 0
    articles_with_20_citations = 0
    articles_with_30_citations = 0
    articles_with_50_citations = 0

    affiliations_freq = Counter()
    countries_freq = Counter()
    single_country_articles = 0
    multi_country_articles = 0
    no_country_articles = 0
    all_authors = []
    all_affiliations = []
    all_countries = []
    
    journal_freq = Counter()
    publisher_freq = Counter()

    for meta in metadata_list:
        if not meta:
            continue

        cr = meta.get('crossref')
        if cr:
            refs = cr.get('reference', [])
            total_refs += len(refs)
            for ref in refs:
                ref_doi = ref.get('DOI', '')
                if ref_doi:
                    refs_with_doi += 1
                    if get_doi_prefix(ref_doi) == journal_prefix:
                        self_cites += 1
                else:
                    refs_without_doi += 1
            ref_counts.append(len(refs))

            authors = cr.get('author', [])
            num_auth = len(authors)
            author_counts.append(num_auth)
            if num_auth == 1:
                single_authors += 1
            if num_auth > 10:
                multi_authors_gt10 += 1

            for auth in authors:
                family = auth.get('family', '').strip().title()
                given = auth.get('given', '').strip()
                initials = '.'.join([c + '.' for c in given if c.isupper()]) if given else ''
                if initials:
                    name = f"{family} {initials}"
                else:
                    name = family or 'Unknown'
                author_freq[name] += 1

            date_parts = cr.get('published', {}).get('date-parts', [[datetime.now().year]])[0]
            pub_date = datetime(date_parts[0], date_parts[1] if len(date_parts)>1 else 1, date_parts[2] if len(date_parts)>2 else 1)
            pub_dates.append(pub_date)
            
            journal_name = cr.get('container-title', [''])[0] if cr.get('container-title') else ''
            publisher = cr.get('publisher', '')
            if journal_name:
                journal_freq[journal_name] += 1
            if publisher:
                publisher_freq[publisher] += 1

        oa = meta.get('openalex')
        if oa:
            try:
                authors_list, affiliations_list, countries_list = extract_affiliations_and_countries(oa)
                
                all_authors.extend(authors_list)
                all_affiliations.extend(affiliations_list)
                all_countries.extend(countries_list)
                
                for aff in affiliations_list:
                    affiliations_freq[aff] += 1
                for country in countries_list:
                    countries_freq[country] += 1
                
                unique_countries = set(countries_list)
                if len(unique_countries) == 0:
                    no_country_articles += 1
                elif len(unique_countries) == 1:
                    single_country_articles += 1
                elif len(unique_countries) > 1:
                    multi_country_articles += 1
                
                host_venue = oa.get('host_venue', {})
                if host_venue:
                    journal_name = host_venue.get('display_name', '')
                    publisher = host_venue.get('publisher', '')
                    if journal_name and journal_name not in journal_freq:
                        journal_freq[journal_name] += 1
                    if publisher and publisher not in publisher_freq:
                        publisher_freq[publisher] += 1
                
                if is_analyzed:
                    citation_count = oa.get('cited_by_count', 0)
                    if citation_count >= 10:
                        articles_with_10_citations += 1
                    if citation_count >= 20:
                        articles_with_20_citations += 1
                    if citation_count >= 30:
                        articles_with_30_citations += 1
                    if citation_count >= 50:
                        articles_with_50_citations += 1
            except Exception as e:
                # Skip problematic records and continue processing
                print(f"Warning processing OpenAlex data: {e}")
                continue

    n_items = len(metadata_list)

    refs_with_doi_pct = (refs_with_doi / total_refs * 100) if total_refs > 0 else 0
    refs_without_doi_pct = (refs_without_doi / total_refs * 100) if total_refs > 0 else 0
    self_cites_pct = (self_cites / total_refs * 100) if total_refs > 0 else 0

    ref_min = min(ref_counts) if ref_counts else 0
    ref_max = max(ref_counts) if ref_counts else 0
    ref_mean = sum(ref_counts)/n_items if n_items > 0 else 0
    ref_median = sorted(ref_counts)[n_items//2] if n_items > 0 else 0

    auth_min = min(author_counts) if author_counts else 0
    auth_max = max(author_counts) if author_counts else 0
    auth_mean = sum(author_counts)/n_items if n_items > 0 else 0
    auth_median = sorted(author_counts)[n_items//2] if n_items > 0 else 0

    all_authors_sorted = author_freq.most_common()

    all_affiliations_sorted = affiliations_freq.most_common()
    all_countries_sorted = countries_freq.most_common()
    
    single_country_pct = (single_country_articles / n_items * 100) if n_items > 0 else 0
    multi_country_pct = (multi_country_articles / n_items * 100) if n_items > 0 else 0
    no_country_pct = (no_country_articles / n_items * 100) if n_items > 0 else 0

    all_journals_sorted = journal_freq.most_common()
    all_publishers_sorted = publisher_freq.most_common()

    return {
        'n_items': n_items,
        'total_refs': total_refs,
        'refs_with_doi': refs_with_doi, 'refs_with_doi_pct': refs_with_doi_pct,
        'refs_without_doi': refs_without_doi, 'refs_without_doi_pct': refs_without_doi_pct,
        'self_cites': self_cites, 'self_cites_pct': self_cites_pct,
        'ref_min': ref_min, 'ref_max': ref_max, 'ref_mean': ref_mean, 'ref_median': ref_median,
        'auth_min': auth_min, 'auth_max': auth_max, 'auth_mean': auth_mean, 'auth_median': auth_median,
        'single_authors': single_authors,
        'multi_authors_gt10': multi_authors_gt10,
        'all_authors': all_authors_sorted,
        'pub_dates': pub_dates,
        'articles_with_10_citations': articles_with_10_citations,
        'articles_with_20_citations': articles_with_20_citations,
        'articles_with_30_citations': articles_with_30_citations,
        'articles_with_50_citations': articles_with_50_citations,
        'all_affiliations': all_affiliations_sorted,
        'all_countries': all_countries_sorted,
        'all_authors_list': all_authors,
        'all_affiliations_list': all_affiliations,
        'all_countries_list': all_countries,
        'single_country_articles': single_country_articles, 
        'single_country_pct': single_country_pct,
        'multi_country_articles': multi_country_articles, 
        'multi_country_pct': multi_country_pct,
        'no_country_articles': no_country_articles,
        'no_country_pct': no_country_pct,
        'total_affiliations_count': len(all_affiliations),
        'unique_affiliations_count': len(set(all_affiliations)),
        'unique_countries_count': len(set(all_countries)),
        'all_journals': all_journals_sorted,
        'all_publishers': all_publishers_sorted,
        'unique_journals_count': len(journal_freq),
        'unique_publishers_count': len(publisher_freq)
    }

# === 14. Enhanced Statistics Calculation ===
def enhanced_stats_calculation(analyzed_metadata, citing_metadata, state):
    citation_network = defaultdict(list)
    citation_counts = []
    
    for analyzed in analyzed_metadata:
        if analyzed and analyzed.get('crossref'):
            analyzed_doi = analyzed['crossref'].get('DOI')
            if analyzed_doi:
                analyzed_year = analyzed['crossref'].get('published', {}).get('date-parts', [[0]])[0][0]
                citings = get_citing_dois_and_metadata((analyzed_doi, state))
                citation_counts.append(len(citings))
                
                for citing in citings:
                    if citing.get('openalex'):
                        citing_year = citing['openalex'].get('publication_year', 0)
                        citation_network[analyzed_year].append(citing_year)
    
    citation_counts.sort(reverse=True)
    h_index = 0
    for i, count in enumerate(citation_counts):
        if count >= i + 1:
            h_index = i + 1
        else:
            break
    
    return {
        'h_index': h_index,
        'citation_network': dict(citation_network),
        'avg_citations_per_article': sum(citation_counts) / len(citation_counts) if citation_counts else 0,
        'max_citations': max(citation_counts) if citation_counts else 0,
        'min_citations': min(citation_counts) if citation_counts else 0,
        'total_citations': sum(citation_counts),
        'articles_with_citations': len([c for c in citation_counts if c > 0]),
        'articles_without_citations': len([c for c in citation_counts if c == 0])
    }

# === 15. Time to First Citation Calculation ===
def calculate_citation_timing_stats(analyzed_metadata, state):
    all_days_to_first_citation = []
    citation_timing_stats = {}
    first_citation_details = []
    
    for analyzed in analyzed_metadata:
        if analyzed and analyzed.get('crossref'):
            analyzed_doi = analyzed['crossref'].get('DOI')
            if not analyzed_doi:
                continue
                
            analyzed_date_parts = analyzed['crossref'].get('published', {}).get('date-parts', [[]])[0]
            if not analyzed_date_parts or len(analyzed_date_parts) < 1:
                continue
                
            analyzed_year = analyzed_date_parts[0]
            analyzed_month = analyzed_date_parts[1] if len(analyzed_date_parts) > 1 else 1
            analyzed_day = analyzed_date_parts[2] if len(analyzed_date_parts) > 2 else 1
            
            try:
                analyzed_date = datetime(analyzed_year, analyzed_month, analyzed_day)
            except:
                continue
            
            citings = get_citing_dois_and_metadata((analyzed_doi, state))
            citation_dates = []
            
            for citing in citings:
                if citing.get('pub_date'):
                    try:
                        cite_date = datetime.fromisoformat(citing['pub_date'].replace('Z', '+00:00'))
                        citation_dates.append((cite_date, citing.get('doi')))
                    except:
                        continue
            
            if citation_dates:
                first_citation_date, first_citing_doi = min(citation_dates, key=lambda x: x[0])
                days_to_first_citation = (first_citation_date - analyzed_date).days
                
                # === ИСКЛЮЧЕНИЕ РЕДАКТОРСКИХ ЗАМЕТОК ===
                # Проверяем, не является ли цитирующая статья редакторской заметкой
                # (имеет тот же DOI-префикс и ту же дату публикации)
                analyzed_prefix = get_doi_prefix(analyzed_doi)
                citing_prefix = get_doi_prefix(first_citing_doi)
                
                same_prefix = (analyzed_prefix == citing_prefix)
                same_date = (analyzed_date.date() == first_citation_date.date())
                
                # Исключаем записи с тем же префиксом и той же датой (вероятно редакторские заметки)
                if not (same_prefix and same_date) and days_to_first_citation >= 0:
                    all_days_to_first_citation.append(days_to_first_citation)
                    first_citation_details.append({
                        'analyzed_doi': analyzed_doi,
                        'citing_doi': first_citing_doi,
                        'analyzed_date': analyzed_date,
                        'first_citation_date': first_citation_date,
                        'days_to_first_citation': days_to_first_citation,
                        'same_prefix': same_prefix,
                        'same_date': same_date
                    })
    
    if all_days_to_first_citation:
        citation_timing_stats = {
            'min_days_to_first_citation': min(all_days_to_first_citation),
            'max_days_to_first_citation': max(all_days_to_first_citation),
            'mean_days_to_first_citation': np.mean(all_days_to_first_citation),
            'median_days_to_first_citation': np.median(all_days_to_first_citation),
            'articles_with_citation_timing_data': len(all_days_to_first_citation),
            'first_citation_details': first_citation_details
        }
    else:
        citation_timing_stats = {
            'min_days_to_first_citation': 0,
            'max_days_to_first_citation': 0,
            'mean_days_to_first_citation': 0,
            'median_days_to_first_citation': 0,
            'articles_with_citation_timing_data': 0,
            'first_citation_details': []
        }
    
    return citation_timing_stats

# === 16. Citation Timing Calculation ===
def calculate_citation_timing(analyzed_metadata, state):
    timing_stats = calculate_citation_timing_stats(analyzed_metadata, state)
    accumulation_stats = analyze_citation_accumulation(analyzed_metadata, state)
    
    return {
        'days_min': timing_stats['min_days_to_first_citation'],
        'days_max': timing_stats['max_days_to_first_citation'],
        'days_mean': timing_stats['mean_days_to_first_citation'],
        'days_median': timing_stats['median_days_to_first_citation'],
        'articles_with_timing_data': timing_stats['articles_with_citation_timing_data'],
        'first_citation_details': timing_stats['first_citation_details'],
        'accumulation_curves': accumulation_stats['accumulation_curves'],
        'yearly_citations': accumulation_stats['yearly_citations'],
        'total_years_covered': accumulation_stats['total_years_covered']
    }

# === NEW FUNCTIONS: FAST METRICS WITHOUT API REQUESTS ===

def calculate_reference_age_fast(analyzed_metadata, state):
    """Reference age calculation without additional API requests"""
    ref_ages = []
    current_year = datetime.now().year
    
    for meta in analyzed_metadata:
        cr = meta.get('crossref')
        if not cr: 
            continue
        
        pub_year = cr.get('published', {}).get('date-parts', [[0]])[0][0]
        if not pub_year: 
            continue
        
        for ref in cr.get('reference', []):
            # 1. Try year from unstructured
            if 'year' in ref:
                try:
                    ref_year = int(ref['year'])
                    if 1900 <= ref_year <= current_year + 1:
                        ref_ages.append(current_year - ref_year)
                        continue
                except: 
                    pass
            
            # 2. Try DOI from cache (already loaded!)
            doi = ref.get('DOI')
            if doi and doi in state.crossref_cache:
                cached = state.crossref_cache[doi]
                date_parts = cached.get('published', {}).get('date-parts', [[0]])[0]
                if date_parts and date_parts[0]:
                    ref_year = date_parts[0]
                    ref_ages.append(current_year - ref_year)
    
    if not ref_ages: 
        return {
            'ref_median_age': None,
            'ref_mean_age': None,
            'ref_ages_25_75': [None, None],
            'total_refs_analyzed': 0
        }
    
    return {
        'ref_median_age': int(np.median(ref_ages)),
        'ref_mean_age': round(np.mean(ref_ages), 1),
        'ref_ages_25_75': [int(np.percentile(ref_ages, 25)), int(np.percentile(ref_ages, 75))],
        'total_refs_analyzed': len(ref_ages)
    }

def calculate_jscr_fast(citing_metadata, journal_issn):
    """Journal Self-Citation Rate - percentage of journal self-citations"""
    if not citing_metadata:
        return {
            'JSCR': 0,
            'self_cites': 0,
            'total_cites': 0,
            'debug': 'No citing metadata'
        }
    
    self_cites = 0
    total_processed = 0
    debug_info = []
    
    # Normalize ISSN for comparison
    journal_issn_clean = journal_issn.replace('-', '').upper() if journal_issn else ""
    
    for i, c in enumerate(citing_metadata):
        current_debug = f"Item {i}: "
        
        # Skip records without data
        if not c:
            current_debug += "No data"
            debug_info.append(current_debug)
            continue
            
        oa = c.get('openalex')
        cr = c.get('crossref')
        
        found_match = False
        found_issns = []
        
        # Check OpenAlex data
        if oa:
            host_venue = oa.get('host_venue', {})
            if host_venue:
                oa_issns = host_venue.get('issn', [])
                if isinstance(oa_issns, str):
                    oa_issns = [oa_issns]
                
                for issn in oa_issns:
                    if issn:
                        issn_clean = issn.replace('-', '').upper()
                        found_issns.append(issn_clean)
                        if issn_clean == journal_issn_clean:
                            found_match = True
                            break
        
        # Check Crossref data if not found in OpenAlex
        if not found_match and cr:
            cr_issns = cr.get('ISSN', [])
            if isinstance(cr_issns, str):
                cr_issns = [cr_issns]
                
            for issn in cr_issns:
                if issn:
                    issn_clean = issn.replace('-', '').upper()
                    found_issns.append(issn_clean)
                    if issn_clean == journal_issn_clean:
                        found_match = True
                        break
        
        # Also check by journal name in crossref (additional method)
        if not found_match and cr:
            container_title = cr.get('container-title', [])
            if container_title and journal_issn:
                # If we have journal name, we can try to match
                # but this is less reliable, so use as fallback
                pass
        
        if found_match:
            self_cites += 1
            current_debug += f"SELF-CITE found. ISSNs: {found_issns}"
        else:
            current_debug += f"Not self-cite. ISSNs: {found_issns}"
        
        debug_info.append(current_debug)
        total_processed += 1
    
    # JSCR calculation
    jscr = round(self_cites / total_processed * 100, 2) if total_processed > 0 else 0
    
    result = {
        'JSCR': jscr,
        'self_cites': self_cites,
        'total_cites': total_processed,
        'debug_count': len(debug_info),
        'journal_issn_clean': journal_issn_clean
    }
    
    # Add first part of debug information (first 10 records)
    result['debug_samples'] = debug_info[:10]
    
    return result

def calculate_cited_half_life_fast(analyzed_metadata, state):
    """Cited Half-Life - median time to receive half of citations"""
    half_lives = []
    
    for meta in analyzed_metadata:
        if not meta or not meta.get('crossref'):
            continue
            
        doi = meta['crossref'].get('DOI')
        pub_year = meta['crossref'].get('published', {}).get('date-parts', [[0]])[0][0]
        if not doi or not pub_year: 
            continue
        
        citings = state.citing_cache.get(doi, [])
        if not citings: 
            continue
        
        yearly = defaultdict(int)
        for c in citings:
            # Fix: correct way to get publication year
            if isinstance(c, dict):
                # If this is a dictionary with citation data
                if c.get('openalex'):
                    y = c['openalex'].get('publication_year')
                elif c.get('pub_date'):
                    # Try to extract year from date
                    try:
                        y = int(c['pub_date'][:4])
                    except:
                        y = None
                else:
                    y = None
            else:
                # If this is just a DOI string (fallback)
                y = None
                
            if y: 
                yearly[y] += 1
        
        total = sum(yearly.values())
        if total == 0: 
            continue
            
        cumulative = 0
        target = total / 2
        for y in range(pub_year, pub_year + 50):
            cumulative += yearly[y]
            if cumulative >= target:
                half_lives.append(y - pub_year)
                break
    
    return {
        'cited_half_life_median': int(np.median(half_lives)) if half_lives else None,
        'cited_half_life_mean': round(np.mean(half_lives), 1) if half_lives else None,
        'articles_with_chl': len(half_lives)
    }

def calculate_fwci_fast(analyzed_metadata):
    """Field-Weighted Citation Impact - improved calculation"""
    if not analyzed_metadata:
        return {
            'FWCI': 0,
            'total_cites': 0,
            'expected_cites': 0,
            'articles_with_concepts': 0,
            'method_used': 'no_data'
        }
    
    total_cites = 0
    expected_sum = 0.0
    articles_with_concepts = 0
    articles_processed = 0
    
    # Collect citation and concept data
    concept_citations = {}
    
    for meta in analyzed_metadata:
        oa = meta.get('openalex')
        if not oa: 
            continue
            
        cites = oa.get('cited_by_count', 0)
        total_cites += cites
        articles_processed += 1
        
        concepts = oa.get('concepts', [])
        if concepts:
            # Use top-3 concepts by score
            top_concepts = sorted(concepts, key=lambda x: x.get('score', 0), reverse=True)[:3]
            
            for concept in top_concepts:
                concept_name = concept.get('display_name', 'Unknown')
                concept_score = concept.get('score', 0)
                
                if concept_name not in concept_citations:
                    concept_citations[concept_name] = {
                        'total_cites': 0,
                        'article_count': 0,
                        'total_score': 0
                    }
                
                concept_citations[concept_name]['total_cites'] += cites
                concept_citations[concept_name]['article_count'] += 1
                concept_citations[concept_name]['total_score'] += concept_score
            
            articles_with_concepts += 1
    
    if articles_processed == 0 or total_cites == 0:
        return {
            'FWCI': 0,
            'total_cites': 0,
            'expected_cites': 0,
            'articles_with_concepts': 0,
            'method_used': 'no_citations'
        }
    
    # Expected citations calculation
    if concept_citations:
        # Method 1: based on concept averages
        for concept_data in concept_citations.values():
            if concept_data['article_count'] > 0:
                avg_cites_per_article = concept_data['total_cites'] / concept_data['article_count']
                avg_score = concept_data['total_score'] / concept_data['article_count']
                
                # Weight by concept score
                expected_contribution = avg_cites_per_article * avg_score
                expected_sum += expected_contribution
        
        method_used = 'concept_based'
    else:
        # Method 2: fallback - use global averages by discipline
        # (this is a simplification, real FWCI uses normalized data)
        
        # Assume basic expectations by article types
        for meta in analyzed_metadata:
            oa = meta.get('openalex')
            if not oa:
                continue
                
            # Simple heuristic approach
            cites = oa.get('cited_by_count', 0)
            work_type = oa.get('type', 'article')
            
            # Basic expectations by publication types
            type_expectations = {
                'article': 1.0,
                'review': 2.0,  # reviews usually cited more
                'conference': 0.7,
                'book': 0.5,
                'other': 0.8
            }
            
            expected = type_expectations.get(work_type, 1.0)
            expected_sum += expected
        
        method_used = 'type_based'
    
    # Normalization of expectations
    if expected_sum == 0:
        expected_sum = articles_processed * 1.0  # Fallback
        method_used = 'fallback'
    
    # FWCI calculation
    fwci = total_cites / expected_sum if expected_sum > 0 else 0
    
    return {
        'FWCI': round(fwci, 2),
        'total_cites': total_cites,
        'expected_cites': round(expected_sum, 2),
        'articles_with_concepts': articles_with_concepts,
        'method_used': method_used,
        'concepts_analyzed': len(concept_citations)
    }

def calculate_citation_velocity_fast(analyzed_metadata, state):
    """Citation Velocity - average citations per year for first 2 years"""
    velocities = []
    current_year = datetime.now().year
    
    for meta in analyzed_metadata:
        cr = meta.get('crossref')
        if not cr: 
            continue
            
        pub_year = cr.get('published', {}).get('date-parts', [[0]])[0][0]
        if current_year - pub_year < 2: 
            continue
        
        citings = state.citing_cache.get(cr.get('DOI'), [])
        early = 0
        
        for c in citings:
            if isinstance(c, dict):
                if c.get('openalex'):
                    citing_year = c['openalex'].get('publication_year', 0)
                elif c.get('pub_date'):
                    try:
                        citing_year = int(c['pub_date'][:4])
                    except:
                        citing_year = 0
                else:
                    citing_year = 0
            else:
                citing_year = 0
                
            if citing_year and citing_year <= pub_year + 2:
                early += 1
                
        velocities.append(early / 2.0)
    
    return {
        'citation_velocity': round(np.mean(velocities), 2) if velocities else 0,
        'articles_with_velocity': len(velocities)
    }

def calculate_oa_impact_premium_fast(analyzed_metadata):
    """Open Access Impact Premium - citation difference between OA and non-OA"""
    oa_citations = []
    non_oa_citations = []
    
    for meta in analyzed_metadata:
        oa = meta.get('openalex')
        if not oa: 
            continue
            
        cites = oa.get('cited_by_count', 0)
        is_oa = oa.get('open_access', {}).get('is_oa', False)
        
        if is_oa:
            oa_citations.append(cites)
        else:
            non_oa_citations.append(cites)
    
    oa_avg = np.mean(oa_citations) if oa_citations else 0
    non_oa_avg = np.mean(non_oa_citations) if non_oa_citations else 0
    
    premium = ((oa_avg - non_oa_avg) / non_oa_avg * 100) if non_oa_avg > 0 else 0
    
    return {
        'OA_impact_premium': round(premium, 1),
        'OA_articles': len(oa_citations),
        'non_OA_articles': len(non_oa_citations),
        'OA_avg_citations': round(oa_avg, 1),
        'non_OA_avg_citations': round(non_oa_avg, 1)
    }

def calculate_elite_index_fast(analyzed_metadata):
    """Elite Index - percentage of articles in top-10% by citations"""
    if not analyzed_metadata:
        return {'elite_index': 0}
    
    citations = []
    for meta in analyzed_metadata:
        oa = meta.get('openalex')
        if oa:
            cites = oa.get('cited_by_count', 0)
            citations.append(cites)
    
    if not citations:
        return {'elite_index': 0}
    
    # DIAGNOSTICS: output citation statistics
    print(f"🔍 Elite Index diagnostics:")
    print(f"   Total articles with citation data: {len(citations)}")
    print(f"   Citation distribution: min={min(citations)}, max={max(citations)}, mean={np.mean(citations):.1f}, median={np.median(citations)}")
    
    # Problem: np.percentile(citations, 90) always gives 90th percentile WITHIN our dataset
    # But Elite Index should be compared with GLOBAL data
    
    # Temporary solution: use heuristic based on distribution
    if max(citations) == 0:
        return {'elite_index': 0}
    
    # Alternative approach 1: count top-10% from maximum value
    max_citations = max(citations)
    threshold_alt1 = max_citations * 0.1  # 10% of maximum
    
    # Alternative approach 2: use quantiles more aggressively
    threshold_alt2 = int(np.percentile(citations, 85))  # More strict threshold
    
    # Alternative approach 3: based on standard deviation
    if len(citations) > 1:
        mean_cites = np.mean(citations)
        std_cites = np.std(citations)
        threshold_alt3 = mean_cites + std_cites  # Articles above average + one standard deviation
    else:
        threshold_alt3 = max(citations)
    
    # Use the most meaningful approach
    threshold = threshold_alt3
    
    elite_count = sum(1 for c in citations if c >= threshold)
    elite_index = round(elite_count / len(citations) * 100, 2)
    
    print(f"   Thresholds: percent90={np.percentile(citations, 90):.1f}, alt1={threshold_alt1:.1f}, alt2={threshold_alt2:.1f}, alt3={threshold_alt3:.1f}")
    print(f"   Result: elite_count={elite_count}, elite_index={elite_index}%")
    
    return {
        'elite_index': elite_index,
        'elite_articles': elite_count,
        'total_articles': len(citations),
        'citation_threshold': int(threshold),
        'method_used': 'mean_plus_std',
        'debug_info': {
            'percentile_90': np.percentile(citations, 90),
            'max_citations': max(citations),
            'mean_citations': np.mean(citations),
            'median_citations': np.median(citations)
        }
    }

def calculate_author_gini_fast(analyzed_metadata):
    """Author Gini Index - inequality index of publication distribution among authors"""
    author_counts = Counter()
    
    for meta in analyzed_metadata:
        oa = meta.get('openalex')
        if oa and 'authorships' in oa:
            for auth in oa['authorships']:
                author_id = auth.get('author', {}).get('id')
                if author_id:
                    author_counts[author_id] += 1
    
    if len(author_counts) < 2:
        return {'author_gini': 0}
    
    # Gini index calculation
    values = sorted(author_counts.values())
    n = len(values)
    cumulative = np.cumsum(values).astype(float)
    gini = (n + 1 - 2 * np.sum(cumulative) / cumulative[-1]) / n
    
    return {
        'author_gini': round(gini, 3),
        'total_authors': len(author_counts),
        'articles_per_author_avg': round(np.mean(values), 2),
        'articles_per_author_median': int(np.median(values))
    }

def calculate_dbi_fast(analyzed_metadata):
    """Diversity Balance Index - thematic diversification index"""
    concept_freq = Counter()
    total_concepts = 0
    
    for meta in analyzed_metadata:
        oa = meta.get('openalex')
        if oa and 'concepts' in oa:
            concepts = oa['concepts']
            # === ИЗМЕНЕНИЕ: расширяем до 10 терминов ===
            for concept in concepts[:10]:  # Take top-10 concepts
                concept_name = concept.get('display_name', '')
                if concept_name:
                    concept_freq[concept_name] += 1
                    total_concepts += 1
    
    if total_concepts == 0:
        return {'DBI': 0}
    
    # Shannon index
    proportions = [count / total_concepts for count in concept_freq.values()]
    shannon = -sum(p * np.log(p) for p in proportions if p > 0)
    
    # Normalization (maximum = log(n))
    max_shannon = np.log(len(concept_freq)) if concept_freq else 1
    dbi = shannon / max_shannon if max_shannon > 0 else 0
    
    return {
        'DBI': round(dbi, 3),
        'unique_concepts': len(concept_freq),
        'total_concept_mentions': total_concepts,
        # === ИЗМЕНЕНИЕ: расширяем до 10 терминов ===
        'top_concepts': concept_freq.most_common(10)
    }

def calculate_all_fast_metrics(analyzed_metadata, citing_metadata, state, journal_issn):
    """Calculation of all fast metrics in one pass with comprehensive error handling"""
    fast_metrics = {}
    
    # 1. Reference Age metrics
    try:
        reference_age_metrics = calculate_reference_age_fast(analyzed_metadata, state)
        fast_metrics.update(reference_age_metrics)
    except Exception as e:
        st.warning(f"⚠️ Reference Age calculation failed: {str(e)}")
        fast_metrics.update({
            'ref_median_age': None,
            'ref_mean_age': None,
            'ref_ages_25_75': [None, None],
            'total_refs_analyzed': 0
        })
    
    # 2. JSCR metrics with enhanced debugging
    try:
        jscr_metrics = calculate_jscr_fast(citing_metadata, journal_issn)
        fast_metrics.update(jscr_metrics)
        
        # Enhanced debug output
        debug_info = []
        debug_info.append(f"=== JSCR DEBUG ===")
        debug_info.append(f"Journal ISSN: {journal_issn}")
        debug_info.append(f"Clean ISSN: {jscr_metrics.get('journal_issn_clean', 'N/A')}")
        debug_info.append(f"Total citing works processed: {jscr_metrics.get('total_cites', 0)}")
        debug_info.append(f"Self-cites found: {jscr_metrics.get('self_cites', 0)}")
        debug_info.append(f"JSCR: {jscr_metrics.get('JSCR', 0)}%")
        
        # Log first few debug samples if available
        if 'debug_samples' in jscr_metrics and jscr_metrics['debug_samples']:
            debug_info.append("First 5 items analysis:")
            for i, debug in enumerate(jscr_metrics['debug_samples'][:5]):
                debug_info.append(f"  {i+1}. {debug}")
        
        # Print debug info to console
        print("\n".join(debug_info))
        
    except Exception as e:
        st.warning(f"⚠️ JSCR calculation failed: {str(e)}")
        fast_metrics.update({
            'JSCR': 0,
            'self_cites': 0,
            'total_cites': 0,
            'journal_issn_clean': journal_issn.replace('-', '').upper() if journal_issn else ""
        })
    
    # 3. Cited Half-Life metrics with robust error handling
    try:
        cited_half_life_metrics = calculate_cited_half_life_fast(analyzed_metadata, state)
        fast_metrics.update(cited_half_life_metrics)
    except Exception as e:
        st.warning(f"⚠️ Cited Half-Life calculation failed: {str(e)}")
        fast_metrics.update({
            'cited_half_life_median': None,
            'cited_half_life_mean': None,
            'articles_with_chl': 0
        })
    
    # 4. Field-Weighted Citation Impact
    try:
        fwci_metrics = calculate_fwci_fast(analyzed_metadata)
        fast_metrics.update(fwci_metrics)
    except Exception as e:
        st.warning(f"⚠️ FWCI calculation failed: {str(e)}")
        fast_metrics.update({
            'FWCI': 0,
            'total_cites_fwci': 0,
            'expected_cites': 0,
            'articles_with_concepts': 0
        })
    
    # 5. Citation Velocity with data validation
    try:
        citation_velocity_metrics = calculate_citation_velocity_fast(analyzed_metadata, state)
        fast_metrics.update(citation_velocity_metrics)
    except Exception as e:
        st.warning(f"⚠️ Citation Velocity calculation failed: {str(e)}")
        fast_metrics.update({
            'citation_velocity': 0,
            'articles_with_velocity': 0
        })
    
    # 6. Open Access Impact Premium
    try:
        oa_impact_premium_metrics = calculate_oa_impact_premium_fast(analyzed_metadata)
        fast_metrics.update(oa_impact_premium_metrics)
    except Exception as e:
        st.warning(f"⚠️ OA Impact Premium calculation failed: {str(e)}")
        fast_metrics.update({
            'OA_impact_premium': 0,
            'OA_articles': 0,
            'non_OA_articles': 0,
            'OA_avg_citations': 0,
            'non_OA_avg_citations': 0
        })
    
    # 7. Elite Index
    try:
        elite_index_metrics = calculate_elite_index_fast(analyzed_metadata)
        fast_metrics.update(elite_index_metrics)
    except Exception as e:
        st.warning(f"⚠️ Elite Index calculation failed: {str(e)}")
        fast_metrics.update({
            'elite_index': 0,
            'elite_articles': 0,
            'total_articles_elite': 0,
            'citation_threshold': 0
        })
    
    # 8. Author Gini Index
    try:
        author_gini_metrics = calculate_author_gini_fast(analyzed_metadata)
        fast_metrics.update(author_gini_metrics)
    except Exception as e:
        st.warning(f"⚠️ Author Gini calculation failed: {str(e)}")
        fast_metrics.update({
            'author_gini': 0,
            'total_authors': 0,
            'articles_per_author_avg': 0,
            'articles_per_author_median': 0
        })
    
    # 9. Diversity Balance Index
    try:
        dbi_metrics = calculate_dbi_fast(analyzed_metadata)
        fast_metrics.update(dbi_metrics)
    except Exception as e:
        st.warning(f"⚠️ DBI calculation failed: {str(e)}")
        fast_metrics.update({
            'DBI': 0,
            'unique_concepts': 0,
            'total_concept_mentions': 0,
            'top_concepts': []
        })
    
    # 10. Additional diagnostic information (with safe array handling)
    try:
        # Add summary statistics for debugging
        fast_metrics['diagnostic_info'] = {
            'analyzed_articles_count': len(analyzed_metadata),
            'citing_articles_count': len(citing_metadata),
            'citing_cache_size': len(state.citing_cache),
            'successful_metrics': len([k for k in fast_metrics.keys() if is_valid_value(fast_metrics[k])])
        }
        
        # Calculate overall data quality score with safe array handling
        quality_indicators = []
        
        # Safe checks for each indicator
        refs_analyzed = fast_metrics.get('total_refs_analyzed', 0)
        quality_indicators.append(refs_analyzed > 0 if not hasattr(refs_analyzed, 'size') else refs_analyzed.size > 0)
        
        total_cites = fast_metrics.get('total_cites', 0)
        quality_indicators.append(total_cites > 0 if not hasattr(total_cites, 'size') else total_cites.size > 0)
        
        articles_chl = fast_metrics.get('articles_with_chl', 0)
        quality_indicators.append(articles_chl > 0 if not hasattr(articles_chl, 'size') else articles_chl.size > 0)
        
        articles_velocity = fast_metrics.get('articles_with_velocity', 0)
        quality_indicators.append(articles_velocity > 0 if not hasattr(articles_velocity, 'size') else articles_velocity.size > 0)
        
        oa_articles = fast_metrics.get('OA_articles', 0)
        non_oa_articles = fast_metrics.get('non_OA_articles', 0)
        oa_check = (oa_articles > 0 if not hasattr(oa_articles, 'size') else oa_articles.size > 0)
        non_oa_check = (non_oa_articles > 0 if not hasattr(non_oa_articles, 'size') else non_oa_articles.size > 0)
        quality_indicators.append(oa_check or non_oa_check)
        
        total_authors = fast_metrics.get('total_authors', 0)
        quality_indicators.append(total_authors > 0 if not hasattr(total_authors, 'size') else total_authors.size > 0)
        
        unique_concepts = fast_metrics.get('unique_concepts', 0)
        quality_indicators.append(unique_concepts > 0 if not hasattr(unique_concepts, 'size') else unique_concepts.size > 0)
        
        # Calculate quality score safely
        if quality_indicators:
            quality_score = sum(quality_indicators) / len(quality_indicators) * 100
            fast_metrics['data_quality_score'] = round(quality_score, 1)
        else:
            fast_metrics['data_quality_score'] = 0
        
    except Exception as e:
        st.warning(f"⚠️ Diagnostic information calculation failed: {str(e)}")
        fast_metrics.update({
            'diagnostic_info': {'error': str(e)},
            'data_quality_score': 0
        })
    
    # 11. Final validation and cleanup
    try:
        # Ensure all expected keys are present with safe defaults
        expected_keys = {
            'ref_median_age', 'ref_mean_age', 'ref_ages_25_75', 'total_refs_analyzed',
            'JSCR', 'self_cites', 'total_cites', 'journal_issn_clean',
            'cited_half_life_median', 'cited_half_life_mean', 'articles_with_chl',
            'FWCI', 'total_cites_fwci', 'expected_cites', 'articles_with_concepts',
            'citation_velocity', 'articles_with_velocity',
            'OA_impact_premium', 'OA_articles', 'non_OA_articles', 'OA_avg_citations', 'non_OA_avg_citations',
            'elite_index', 'elite_articles', 'total_articles_elite', 'citation_threshold',
            'author_gini', 'total_authors', 'articles_per_author_avg', 'articles_per_author_median',
            'DBI', 'unique_concepts', 'total_concept_mentions', 'top_concepts',
            'data_quality_score'
        }
        
        for key in expected_keys:
            if key not in fast_metrics:
                if key == 'ref_ages_25_75':
                    fast_metrics[key] = [None, None]
                elif key == 'top_concepts':
                    fast_metrics[key] = []
                elif 'pct' in key or 'rate' in key or 'index' in key or 'premium' in key:
                    fast_metrics[key] = 0.0
                else:
                    fast_metrics[key] = 0
        
        # Clean up any None values and convert numpy types to Python types
        for key in list(fast_metrics.keys()):
            value = fast_metrics[key]
            
            # Handle numpy arrays and types
            if hasattr(value, 'item'):  # numpy scalar
                try:
                    fast_metrics[key] = value.item()
                except:
                    fast_metrics[key] = 0
            elif hasattr(value, 'size'):  # numpy array
                if value.size == 0:
                    fast_metrics[key] = [] if key == 'top_concepts' else 0
                elif value.size == 1:
                    try:
                        fast_metrics[key] = value.item()
                    except:
                        fast_metrics[key] = 0
                else:
                    fast_metrics[key] = value.tolist() if key == 'ref_ages_25_75' else 0
            
            # Handle None values
            elif value is None:
                if key == 'ref_ages_25_75':
                    fast_metrics[key] = [None, None]
                elif key == 'top_concepts':
                    fast_metrics[key] = []
                elif isinstance(value, (int, float)):
                    fast_metrics[key] = 0
                else:
                    fast_metrics[key] = 0
        
    except Exception as e:
        st.error(f"❌ Final validation failed: {str(e)}")
    
    # 12. Log completion with safe value checking
    try:
        successful_calculations = len([k for k in fast_metrics.keys() if is_valid_value(fast_metrics[k])])
        total_calculations = len(fast_metrics)
        
        print(f"✅ Fast metrics calculation completed: {successful_calculations}/{total_calculations} successful")
        print(f"📊 Data quality score: {fast_metrics.get('data_quality_score', 0)}%")
        
    except Exception as e:
        print(f"⚠️ Completion logging failed: {str(e)}")
    
    return fast_metrics

def is_valid_value(value):
    """Safe function to check if a value is valid (not empty/zero/None)"""
    try:
        if value is None:
            return False
        
        # Handle numpy arrays and types
        if hasattr(value, 'size'):
            if value.size == 0:
                return False
            elif value.size == 1:
                return value.item() not in [0, None]
            else:
                return True
        
        # Handle regular Python types
        if isinstance(value, (list, tuple, dict)):
            return len(value) > 0
        elif isinstance(value, (int, float)):
            return value != 0
        elif isinstance(value, str):
            return value != ""
        else:
            return value not in [0, None, [], ""]
    
    except Exception:
        return False

# === NEW FUNCTIONS FOR ADDITIONAL FEATURES ===

def normalize_issn_for_comparison(issn):
    """Normalize ISSN for comparison"""
    if not issn:
        return ""

    # Convert to string if it's a float or other numeric type
    if isinstance(issn, (float, int)):
        # Handle NaN values and convert to string without decimal for integers
        if pd.isna(issn):
            return ""
        issn_str = str(int(issn)) if isinstance(issn, float) and issn.is_integer() else str(issn)
    else:
        issn_str = str(issn)
    
    # Remove any hyphens and spaces
    clean_issn = issn_str.replace('-', '').replace(' ', '')

    # Remove any decimal points if present (for float conversion)
    clean_issn = clean_issn.replace('.', '')
    
    # === FIX: Add leading zeros for 7-digit ISSNs ===
    if len(clean_issn) == 7:
        clean_issn = '0' + clean_issn  # Add leading zero
    
    # Pad with leading zeros to make 8 digits
    normalized = clean_issn.zfill(8)
    
    return normalized

def load_metrics_data():
    """Load IF and CS data from Excel files"""
    state = get_analysis_state()
    
    # Load IF data (Web of Science)
    try:
        if os.path.exists('IF.xlsx'):
            state.if_data = pd.read_excel('IF.xlsx')
            # Removed success message to avoid showing in interface
        else:
            # Removed warning message to avoid showing in interface
            state.if_data = pd.DataFrame()
    except Exception as e:
        # Removed error message to avoid showing in interface
        state.if_data = pd.DataFrame()
    
    # Load CS data (Scopus) - UPDATED: Now loading CS.xlsx
    try:
        if os.path.exists('CS.xlsx'):
            state.cs_data = pd.read_excel('CS.xlsx')
            # Removed success message to avoid showing in interface
        else:
            # Removed warning message to avoid showing in interface
            state.cs_data = pd.DataFrame()
    except Exception as e:
        # Removed error message to avoid showing in interface
        state.cs_data = pd.DataFrame()

def get_journal_metrics(journal_issns):
    """Get metrics for a journal based on its ISSNs"""
    state = get_analysis_state()
    
    if_metrics = {}
    cs_metrics = {}
    
    # Process each ISSN to find matches
    for issn in journal_issns:
        if not issn or pd.isna(issn):
            continue
            
        normalized_issn = normalize_issn_for_comparison(issn)
        print(f"🔍 Searching for ISSN: {issn} -> normalized: {normalized_issn}")
        
        # Search in Web of Science data (IF)
        if not state.if_data.empty and not if_metrics:  # Only search if not already found
            # Apply normalization with error handling
            def safe_normalize_issn(issn_series):
                try:
                    return issn_series.fillna('').astype(str).apply(normalize_issn_for_comparison)
                except Exception as e:
                    print(f"Error normalizing IF ISSN: {e}")
                    return pd.Series([""] * len(issn_series))
    
            if_match = state.if_data[
                (safe_normalize_issn(state.if_data['ISSN']) == normalized_issn) |
                (safe_normalize_issn(state.if_data['eISSN']) == normalized_issn)
            ]
            
            if not if_match.empty:
                print(f"✅ Found IF match: {len(if_match)} records")
                if_metrics = {
                    'if': if_match.iloc[0]['IF'],
                    'quartile': if_match.iloc[0]['Quartile']
                }
                # Do NOT break here - continue searching for CS metrics
                  
        # Search in Scopus data (CS) - UPDATED: Now searching in CS.xlsx
        if not state.cs_data.empty and not cs_metrics:  # Only search if not already found
            # Apply normalization for CS data
            def safe_normalize_cs_issn(issn_series):
                try:
                    return issn_series.fillna('').astype(str).apply(normalize_issn_for_comparison)
                except Exception as e:
                    print(f"Error normalizing CS ISSN: {e}")
                    return pd.Series([""] * len(issn_series))
            
            # Search for matches in Print ISSN or E-ISSN columns
            cs_match = state.cs_data[
                (safe_normalize_cs_issn(state.cs_data['Print ISSN']) == normalized_issn) |
                (safe_normalize_cs_issn(state.cs_data['E-ISSN']) == normalized_issn)
            ]
            
            if not cs_match.empty:
                print(f"✅ Found CS match: {len(cs_match)} records")
                # Handle duplicates - take the best quartile (lowest number)
                best_quartile = cs_match['Quartile'].min()
                corresponding_citescore = cs_match[cs_match['Quartile'] == best_quartile]['CiteScore'].iloc[0]
                
                cs_metrics = {
                    'citescore': corresponding_citescore,
                    'quartile': f"Q{int(best_quartile)}"
                }
                # Do NOT break here - continue processing other ISSNs if needed
    
        # If we found both metrics, we can stop early
        if if_metrics and cs_metrics:
            break

    print(f"🎯 Final metrics - IF: {if_metrics}, CS: {cs_metrics}")

    return {
        'if_metrics': if_metrics,
        'cs_metrics': cs_metrics
    }

def analyze_citation_seasonality(analyzed_metadata, state, median_days_to_first_citation):
    """Analyze citation seasonality and predict optimal publication months"""
    citation_months = Counter()
    publication_months = Counter()
    
    # Collect citation months
    for analyzed in analyzed_metadata:
        if analyzed and analyzed.get('crossref'):
            analyzed_doi = analyzed['crossref'].get('DOI')
            if not analyzed_doi:
                continue
                
            citings = state.citing_cache.get(analyzed_doi, [])
            
            for citing in citings:
                if citing.get('pub_date'):
                    try:
                        cite_date = datetime.fromisoformat(citing['pub_date'].replace('Z', '+00:00'))
                        citation_months[cite_date.month] += 1
                    except:
                        continue
    
    # Collect publication months of analyzed articles
    for analyzed in analyzed_metadata:
        if analyzed and analyzed.get('crossref'):
            date_parts = analyzed['crossref'].get('published', {}).get('date-parts', [[]])[0]
            if len(date_parts) >= 2:  # Has at least year and month
                publication_months[date_parts[1]] += 1
    
    # Calculate optimal publication months based on citation seasonality and median time to first citation
    optimal_months = []
    if citation_months and median_days_to_first_citation > 0:
        # Find months with highest citations
        top_citation_months = [month for month, count in citation_months.most_common(3)]
        
        # Calculate recommended publication months (considering median time to first citation)
        for citation_month in top_citation_months:
            # Calculate when to publish to get citations in high-citation months
            days_to_subtract = median_days_to_first_citation
            recommended_publication_month = int((citation_month - (days_to_subtract // 30)) % 12)
            if recommended_publication_month == 0:
                recommended_publication_month = 12
            
            optimal_months.append({
                'citation_month': citation_month,
                'citation_count': citation_months[citation_month],
                'recommended_publication_month': recommended_publication_month,
                'reasoning': f"Publish in month {recommended_publication_month} to receive citations in high-citation month {citation_month} (considering {median_days_to_first_citation} days median time to first citation)"
            })
    
    return {
        'citation_months': dict(citation_months),
        'publication_months': dict(publication_months),
        'optimal_publication_months': optimal_months,
        'total_citations_by_month': sum(citation_months.values())
    }

def find_potential_reviewers(analyzed_metadata, citing_metadata, overlap_details, state):
    """Find potential reviewers from citing authors who never published in the journal"""
    
    # Get all authors from analyzed articles (journal authors)
    journal_authors = set()
    for analyzed in analyzed_metadata:
        if analyzed and analyzed.get('openalex'):
            authors, _, _ = extract_affiliations_and_countries(analyzed.get('openalex'))
            journal_authors.update(authors)
    
    # Get overlap authors (those who already have connections with the journal)
    overlap_authors = set()
    for overlap in overlap_details:
        overlap_authors.update(overlap['common_authors'])
    
    # Find citing authors who are NOT in journal authors and NOT in overlap authors
    potential_reviewer_candidates = Counter()
    reviewer_citation_details = defaultdict(list)
    
    for citing in citing_metadata:
        if not citing or not citing.get('openalex'):
            continue
            
        authors, _, _ = extract_affiliations_and_countries(citing.get('openalex'))
        citing_doi = citing.get('doi', 'Unknown DOI')
        
        for author in authors:
            # Check if author is NOT a journal author and NOT an overlap author
            if author not in journal_authors and author not in overlap_authors and author != 'Unknown':
                potential_reviewer_candidates[author] += 1
                reviewer_citation_details[author].append(citing_doi)
    
    # Prepare detailed results - filter out authors with only 1 citation
    potential_reviewers = []
    for author, citation_count in potential_reviewer_candidates.most_common():
        if citation_count > 1:  # Only include authors with more than 1 citation
            potential_reviewers.append({
                'author': author,
                'citation_count': citation_count,
                'citing_dois': reviewer_citation_details[author]  # Keep all DOIs for detailed analysis
            })
    
    return {
        'potential_reviewers': potential_reviewers,
        'total_journal_authors': len(journal_authors),
        'total_overlap_authors': len(overlap_authors),
        'total_potential_reviewers': len(potential_reviewers)
    }

# === NEW CLASS FOR TITLE KEYWORDS ANALYSIS ===
class TitleKeywordsAnalyzer:
    def __init__(self):
        # Инициализация стоп-слов и стеммера
        try:
            import nltk
            from nltk.corpus import stopwords
            from nltk.stem import PorterStemmer
            
            # Загружаем стоп-слова
            nltk.download('stopwords', quiet=True)
            self.stop_words = set(stopwords.words('english'))
            self.stemmer = PorterStemmer()
        except:
            # Fallback если nltk не доступен
            self.stop_words = {'a', 'an', 'the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by'}
            self.stemmer = None
        
        # Научные стоп-слова
        self.scientific_stopwords = {
            'activation', 'adaptive', 'advanced', 'analysis', 'application',
            'applications', 'approach', 'architecture', 'artificial', 'assessment',
            'based', 'behavior', 'capacity', 'characteristics', 'characterization',
            'coating', 'coatings', 'comparative', 'computational', 'composite',
            'composites', 'control', 'cycle', 'damage', 'data', 'density', 'design',
            'detection', 'development', 'device', 'devices', 'diagnosis', 'discovery',
            'dynamic', 'dynamics', 'economic', 'effect', 'effects', 'efficacy',
            'efficient', 'energy', 'engineering', 'enhanced', 'environmental',
            'evaluation', 'experimental', 'exploration', 'factors', 'failure',
            'fabrication', 'field', 'film', 'films', 'flow', 'framework', 'frequency',
            'functional', 'growth', 'high', 'impact', 'improved', 'improvement',
            'induced', 'influence', 'information', 'innovative', 'intelligent',
            'interaction', 'interface', 'interfaces', 'investigation', 'knowledge',
            'layer', 'layers', 'learning', 'magnetic', 'management', 'material',
            'materials', 'measurement', 'mechanism', 'mechanisms', 'medical',
            'method', 'methods', 'model', 'models', 'modification', 'modulation',
            'molecular', 'monitoring', 'motion', 'nanoparticle', 'nanoparticles',
            'nanostructure', 'nanostructures', 'network', 'neural', 'new', 'nonlinear',
            'novel', 'numerical', 'optical', 'optimization', 'pattern', 'performance',
            'phenomenon', 'potential', 'power', 'prediction', 'preparation', 'process',
            'processing', 'production', 'progression', 'property', 'properties',
            'quality', 'regulation', 'relationship', 'reliability', 'remote', 'repair',
            'research', 'resistance', 'response', 'review', 'risk', 'role', 'safety',
            'sample', 'samples', 'scale', 'screening', 'separation', 'signal',
            'simulation', 'specific', 'stability', 'stable', 'state', 'storage',
            'strain', 'strength', 'stress', 'structural', 'structure', 'study',
            'studies', 'sustainable', 'synergy', 'synthesis', 'system', 'systems',
            'targeted', 'techniques', 'technology', 'testing', 'theoretical', 'therapy',
            'thermal', 'tissue', 'tolerance', 'toxicity', 'transformation', 'transition',
            'transmission', 'transport', 'type', 'understanding', 'using', 'validation',
            'value', 'variation', 'virtual', 'waste', 'wave'
        }
        
        # Стемминг научных стоп-слов
        if self.stemmer:
            self.scientific_stopwords_stemmed = {
                self.stemmer.stem(word) for word in self.scientific_stopwords
            }
        else:
            self.scientific_stopwords_stemmed = self.scientific_stopwords
    
    def preprocess_content_words(self, text: str) -> List[str]:
        """Очищает и нормализует содержательные слова (удалено слово 'sub')"""
        if not text or text in ['Название не найдено', 'Таймаут запроса', 'Ошибка сети', 'Ошибка при получении']:
            return []

        text = text.lower()
        text = re.sub(r'[^a-zA-Z\s-]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        words = text.split()
        content_words = []

        for word in words:
            if '-' in word:
                continue
            if len(word) > 2 and word not in self.stop_words:
                if self.stemmer:
                    stemmed_word = self.stemmer.stem(word)
                else:
                    stemmed_word = word
                if stemmed_word not in self.scientific_stopwords_stemmed:
                    content_words.append(stemmed_word)

        return content_words

    def extract_compound_words(self, text: str) -> List[str]:
        """Извлекает составные слова через дефис"""
        if not text or text in ['Название не найдено', 'Таймаут запроса', 'Ошибка сети', 'Ошибка при получении']:
            return []

        text = text.lower()
        compound_words = re.findall(r'\b[a-z]{2,}-[a-z]{2,}(?:-[a-z]{2,})*\b', text)

        filtered_compounds = []
        for word in compound_words:
            parts = word.split('-')
            if not any(part in self.stop_words for part in parts):
                filtered_compounds.append(word)

        return filtered_compounds

    def extract_scientific_stopwords(self, text: str) -> List[str]:
        """Извлекает научные ��топ-слова"""
        if not text or text in ['Название не найдено', 'Таймаут запроса', 'Ошибка сети', 'Ошибка при получении']:
            return []

        text = text.lower()
        text = re.sub(r'[^a-zA-Z\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        words = text.split()
        scientific_words = []

        for word in words:
            if len(word) > 2:
                if self.stemmer:
                    stemmed_word = self.stemmer.stem(word)
                else:
                    stemmed_word = word
                if stemmed_word in self.scientific_stopwords_stemmed:
                    for original_word in self.scientific_stopwords:
                        if self.stemmer:
                            original_stemmed = self.stemmer.stem(original_word)
                        else:
                            original_stemmed = original_word
                        if original_stemmed == stemmed_word:
                            scientific_words.append(original_word)
                            break

        return scientific_words

    def analyze_titles(self, analyzed_titles: List[str], citing_titles: List[str]) -> dict:
        """Анализирует ключевые слова в названиях анализируемых и цитирующих статей"""
        # Анализ анализируемых статей
        analyzed_content_words = []
        analyzed_compound_words = []
        analyzed_scientific_words = []
        
        valid_analyzed_titles = [t for t in analyzed_titles if t and t not in ['Название не найдено', 'Таймаут запроса', 'Ошибка сети', 'Ошибка при получении']]
        
        for title in valid_analyzed_titles:
            analyzed_content_words.extend(self.preprocess_content_words(title))
            analyzed_compound_words.extend(self.extract_compound_words(title))
            analyzed_scientific_words.extend(self.extract_scientific_stopwords(title))
        
        # Анализ цитирующих статей
        citing_content_words = []
        citing_compound_words = []
        citing_scientific_words = []
        
        valid_citing_titles = [t for t in citing_titles if t and t not in ['Название не найдено', 'Таймаут запроса', 'Ошибка сети', 'Ошибка при получении']]
        
        for title in valid_citing_titles:
            citing_content_words.extend(self.preprocess_content_words(title))
            citing_compound_words.extend(self.extract_compound_words(title))
            citing_scientific_words.extend(self.extract_scientific_stopwords(title))
        
        # Подсчет частот
        analyzed_content_freq = Counter(analyzed_content_words)
        analyzed_compound_freq = Counter(analyzed_compound_words)
        analyzed_scientific_freq = Counter(analyzed_scientific_words)
        
        citing_content_freq = Counter(citing_content_words)
        citing_compound_freq = Counter(citing_compound_words)
        citing_scientific_freq = Counter(citing_scientific_words)
        
        # Топ-50 для каждого типа
        top_50_analyzed_content = analyzed_content_freq.most_common(50)
        top_50_analyzed_compound = analyzed_compound_freq.most_common(50)
        top_50_analyzed_scientific = analyzed_scientific_freq.most_common(50)
        
        top_50_citing_content = citing_content_freq.most_common(50)
        top_50_citing_compound = citing_compound_freq.most_common(50)
        top_50_citing_scientific = citing_scientific_freq.most_common(50)
        
        return {
            'analyzed': {
                'content_words': top_50_analyzed_content,
                'compound_words': top_50_analyzed_compound,
                'scientific_words': top_50_analyzed_scientific,
                'total_titles': len(valid_analyzed_titles)
            },
            'citing': {
                'content_words': top_50_citing_content,
                'compound_words': top_50_citing_compound,
                'scientific_words': top_50_citing_scientific,
                'total_titles': len(valid_citing_titles)
            }
        }

def extract_titles_from_metadata(metadata_list):
    """Извлекает названия статей из метаданных"""
    titles = []
    for meta in metadata_list:
        if not meta:
            titles.append('')
            continue
            
        cr = meta.get('crossref')
        oa = meta.get('openalex')
        
        title = ''
        if cr:
            title_list = cr.get('title', [])
            if title_list:
                title = title_list[0]
        elif oa:
            title = oa.get('title', '')
        
        titles.append(title if title else '')
    
    return titles

def normalize_author_name(author_name):
    """Нормализация имени автора - оставляем только первый инициал"""
    if not author_name:
        return author_name
    
    # Убираем лишние точки (исправляем Pikalova E..Y. -> Pikalova E.Y.)
    author_name = re.sub(r'\.\.', '.', author_name)
    
    # Разделяем фамилию и инициалы
    parts = author_name.split()
    if len(parts) < 2:
        return author_name
    
    # Берем фамилию (первая часть) и первый инициал
    surname = parts[0]
    initials = parts[1]
    
    # Берем только первую букву инициалов (первый инициал)
    if '.' in initials:
        # Если инициалы с точками: "E.Y." -> берем "E."
        first_initials = re.findall(r'[A-Z]\.', initials)
        if first_initials:
            first_initial = first_initials[0]
        else:
            # Если формат другой, берем первую букву
            first_initial = initials[0] + '.' if len(initials) > 0 else ''
    else:
        # Если без точек: "EY" -> берем "E."
        first_initial = initials[0] + '.' if len(initials) > 0 else ''
    
    return f"{surname} {first_initial}".strip()

def normalize_keywords_data(keywords_data):
    """Нормализация данных ключевых слов для объединенного листа"""
    normalized_data = []
    
    # Нормализация для content words
    analyzed_total = keywords_data['analyzed']['total_titles']
    citing_total = keywords_data['citing']['total_titles']
    
    # Content words
    for i, (word, analyzed_count) in enumerate(keywords_data['analyzed']['content_words'], 1):
        citing_count = next((c for w, c in keywords_data['citing']['content_words'] if w == word), 0)
        
        # Нормализация частот
        norm_analyzed = analyzed_count / analyzed_total if analyzed_total > 0 else 0
        norm_citing = citing_count / citing_total if citing_total > 0 else 0
        total_norm = norm_analyzed + norm_citing
        ratio = norm_analyzed / norm_citing if norm_citing > 0 else float('inf')
        
        normalized_data.append({
            'Rank': i,
            'Keyword Type': 'Content',
            'Keyword': word,
            'Norm_Analyzed': round(norm_analyzed, 4),
            'Norm_Citing': round(norm_citing, 4),
            'Total_Norm': round(total_norm, 4),
            'Ratio_Analyzed/Citing': round(ratio, 2)
        })
    
    # Compound words
    for i, (word, analyzed_count) in enumerate(keywords_data['analyzed']['compound_words'], 1):
        citing_count = next((c for w, c in keywords_data['citing']['compound_words'] if w == word), 0)
        
        norm_analyzed = analyzed_count / analyzed_total if analyzed_total > 0 else 0
        norm_citing = citing_count / citing_total if citing_total > 0 else 0
        total_norm = norm_analyzed + norm_citing
        ratio = norm_analyzed / norm_citing if norm_citing > 0 else float('inf')
        
        normalized_data.append({
            'Rank': i,
            'Keyword Type': 'Compound',
            'Keyword': word,
            'Norm_Analyzed': round(norm_analyzed, 4),
            'Norm_Citing': round(norm_citing, 4),
            'Total_Norm': round(total_norm, 4),
            'Ratio_Analyzed/Citing': round(ratio, 2)
        })
    
    # Scientific stopwords
    for i, (word, analyzed_count) in enumerate(keywords_data['analyzed']['scientific_words'], 1):
        citing_count = next((c for w, c in keywords_data['citing']['scientific_words'] if w == word), 0)
        
        norm_analyzed = analyzed_count / analyzed_total if analyzed_total > 0 else 0
        norm_citing = citing_count / citing_total if citing_total > 0 else 0
        total_norm = norm_analyzed + norm_citing
        ratio = norm_analyzed / norm_citing if norm_citing > 0 else float('inf')
        
        normalized_data.append({
            'Rank': i,
            'Keyword Type': 'Scientific',
            'Keyword': word,
            'Norm_Analyzed': round(norm_analyzed, 4),
            'Norm_Citing': round(norm_citing, 4),
            'Total_Norm': round(total_norm, 4),
            'Ratio_Analyzed/Citing': round(ratio, 2)
        })
    
    # Сортировка по убыванию Norm_Citing
    normalized_data.sort(key=lambda x: x['Norm_Citing'], reverse=True)
    
    # Обновляем ранги после сортировки
    for i, item in enumerate(normalized_data, 1):
        item['Rank'] = i
    
    return normalized_data

# === 17. Enhanced Excel Report Creation ===
def create_enhanced_excel_report(journal_results, excel_buffer):
    """Create enhanced Excel report with error handling for large data"""

    def safe_convert(value):
        """Safely convert numpy types to Python native types"""
        if value is None:
            return 0
        if hasattr(value, 'item'):
            return value.item()
        elif isinstance(value, (np.integer, np.int32, np.int64)):
            return int(value)
        elif isinstance(value, (np.floating, np.float32, np.float64)):
            return float(value)
        elif isinstance(value, np.bool_):
            return bool(value)
        return value

    def safe_join(items, sep='; ', max_len=None):
        """Safely join list, filtering None and applying length limit"""
        if not items:
            return ''
        cleaned = [str(x).strip() for x in items if x is not None and str(x).strip()]
        result = sep.join(cleaned)
        return result[:max_len] if max_len else result
        
    try:
        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
            # Comparative Statistics sheet for all journals
            comparative_data = []
            journal_names = list(journal_results.keys())
            
            # Define metrics for comparison
            metrics = [
                'n_items', 'total_citations', 'h_index', 'avg_citations_per_article',
                'self_cites_pct', 'multi_country_pct', 'unique_affiliations_count',
                'unique_countries_count', 'ref_mean', 'auth_mean'
            ]
            
            for journal_name in journal_names:
                result = journal_results[journal_name]
                analyzed_stats = result['analyzed_stats']
                enhanced_stats = result['enhanced_stats']
                
                row = {'Journal': journal_name}
                for metric in metrics:
                    if metric in analyzed_stats:
                        row[metric] = safe_convert(analyzed_stats[metric])
                    elif metric in enhanced_stats:
                        row[metric] = safe_convert(enhanced_stats[metric])
                    else:
                        row[metric] = 0
                comparative_data.append(row)
            
            if comparative_data:
                comparative_df = pd.DataFrame(comparative_data)
                comparative_df.to_excel(writer, sheet_name='Comparative_Statistics', index=False)

            # Individual sheets for each journal (simplified)
            MAX_ROWS = 10000  # Reduced for multiple journals
            for journal_name in journal_names:
                result = journal_results[journal_name]
                analyzed_metadata = result['analyzed_metadata']
                all_citing_metadata = result['all_citing_metadata']
                analyzed_stats = result['analyzed_stats']
                citing_stats = result['citing_stats']
                enhanced_stats = result['enhanced_stats']
                citation_timing = result['citation_timing']
                overlap_details = result['overlap_details']

                # Sheet for analyzed articles (per journal)
                analyzed_list = []
                for i, item in enumerate(analyzed_metadata):
                    if i >= MAX_ROWS:
                        break
                    if item and item.get('crossref'):
                        cr = item['crossref']
                        oa = item.get('openalex', {})
                        authors_list, affiliations_list, countries_list = extract_affiliations_and_countries(oa)
                        journal_info = extract_journal_info(item)
                        
                        analyzed_list.append({
                            'DOI': safe_convert(cr.get('DOI', ''))[:100],
                            'Title': (cr.get('title', [''])[0] if cr.get('title') else 'No title')[:200],
                            'Authors': safe_join([f"{a.get('given', '')} {a.get('family', '')}".strip() for a in cr.get('author', []) if a.get('given') or a.get('family')])[:300],
                            'Affiliations': safe_join(affiliations_list)[:500],
                            'Countries': safe_join(countries_list)[:100],
                            'Publication_Year': safe_convert(cr.get('published', {}).get('date-parts', [[0]])[0][0]),
                            'Journal': safe_convert(journal_info['journal_name'])[:100],
                            'Publisher': safe_convert(journal_info['publisher'])[:100],
                            'ISSN': safe_join([str(issn) for issn in journal_info['issn'] if issn])[:50],
                            'Reference_Count': safe_convert(cr.get('reference-count', 0)),
                            'Citations_OpenAlex': safe_convert(oa.get('cited_by_count', 0)) if oa else 0,
                            'Author_Count': safe_convert(len(cr.get('author', []))),
                            'Work_Type': safe_convert(cr.get('type', ''))[:50]
                        })
                
                if analyzed_list:
                    analyzed_df = pd.DataFrame(analyzed_list)
                    analyzed_df.to_excel(writer, sheet_name=f'{journal_name}_Analyzed', index=False)

                # Sheet for citing works (per journal, simplified)
                citing_list = []
                for i, item in enumerate(all_citing_metadata):
                    if i >= MAX_ROWS:
                        break
                    if item and item.get('crossref'):
                        cr = item['crossref']
                        oa = item.get('openalex', {})
                        authors_list, affiliations_list, countries_list = extract_affiliations_and_countries(oa)
                        journal_info = extract_journal_info(item)
                        
                        citing_list.append({
                            'DOI': safe_convert(cr.get('DOI', ''))[:100],
                            'Title': (cr.get('title', [''])[0] if cr.get('title') else 'No title')[:200],
                            'Authors': safe_join([f"{a.get('given', '')} {a.get('family', '')}".strip() for a in cr.get('author', []) if a.get('given') or a.get('family')])[:300],
                            'Affiliations': safe_join(affiliations_list)[:500],
                            'Countries': safe_join(countries_list)[:100],
                            'Publication_Year': safe_convert(cr.get('published', {}).get('date-parts', [[0]])[0][0]),
                            'Journal': safe_convert(journal_info['journal_name'])[:100],
                            'Publisher': safe_convert(journal_info['publisher'])[:100],
                            'ISSN': safe_join([str(issn) for issn in journal_info['issn'] if issn])[:50],
                            'Reference_Count': safe_convert(cr.get('reference-count', 0)),
                            'Citations_OpenAlex': safe_convert(oa.get('cited_by_count', 0)) if oa else 0,
                            'Author_Count': safe_convert(len(cr.get('author', []))),
                            'Work_Type': safe_convert(cr.get('type', ''))[:50]
                        })
                
                if citing_list:
                    citing_df = pd.DataFrame(citing_list)
                    citing_df.to_excel(writer, sheet_name=f'{journal_name}_Citing', index=False)

                # Simplified Statistics sheet per journal
                statistics_data = {
                    'Metric': [
                        'Total Articles', 
                        'Total References', 
                        'Self-Citations Percentage',
                        'Average References',
                        'Average Authors',
                        'International Collaboration %',
                        'Unique Affiliations',
                        'Unique Countries'
                    ],
                    'Value': [
                        safe_convert(analyzed_stats['n_items']),
                        safe_convert(analyzed_stats['total_refs']),
                        f"{safe_convert(analyzed_stats['self_cites_pct']):.1f}%",
                        f"{safe_convert(analyzed_stats['ref_mean']):.1f}",
                        f"{safe_convert(analyzed_stats['auth_mean']):.1f}",
                        f"{safe_convert(analyzed_stats['multi_country_pct']):.1f}%",
                        safe_convert(analyzed_stats['unique_affiliations_count']),
                        safe_convert(analyzed_stats['unique_countries_count'])
                    ]
                }
                statistics_df = pd.DataFrame(statistics_data)
                statistics_df.to_excel(writer, sheet_name=f'{journal_name}_Statistics', index=False)

                # Simplified Citing Stats
                citing_stats_data = {
                    'Metric': [
                        'H-index', 'Total Citations',
                        'Average Citations per Article', 'Articles with Citations'
                    ],
                    'Value': [
                        safe_convert(enhanced_stats['h_index']),
                        safe_convert(enhanced_stats['total_citations']),
                        f"{safe_convert(enhanced_stats['avg_citations_per_article']):.1f}",
                        safe_convert(enhanced_stats['articles_with_citations'])
                    ]
                }
                citing_stats_df = pd.DataFrame(citing_stats_data)
                citing_stats_df.to_excel(writer, sheet_name=f'{journal_name}_Citing_Stats', index=False)

            # Ensure at least one sheet exists
            if len(writer.sheets) == 0:
                summary_df = pd.DataFrame({
                    'Status': ['Analysis completed'],
                    'Message': ['No data matched the criteria. Check ISSN and period.']
                })
                summary_df.to_excel(writer, sheet_name='Summary', index=False)

        excel_buffer.seek(0)
        return True

    except Exception as e:
        st.error(translation_manager.get_text('excel_creation_error').format(error=str(e)))
        # Create minimal report with error
        try:
            excel_buffer.seek(0)
            excel_buffer.truncate(0)
            
            with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                error_df = pd.DataFrame({
                    'Error': [f'{translation_manager.get_text("failed_create_full_report")}: {str(e)}'],
                    'Recommendation': [translation_manager.get_text('try_reduce_data_or_period')]
                })
                error_df.to_excel(writer, sheet_name='Information', index=False)
            
            excel_buffer.seek(0)
            st.warning(translation_manager.get_text('simplified_report_created'))
            return True
            
        except Exception as e2:
            st.error(translation_manager.get_text('critical_excel_error').format(error=str(e2)))
            return False

# === 18. Data Visualization ===
def create_visualizations(journal_results):
    """Create visualizations for dashboard"""
    
    # Create tabs for comparative visualization
    tab1, tab2, tab3 = st.tabs([
        translation_manager.get_text('tab_main_metrics'), 
        translation_manager.get_text('tab_authors_organizations'), 
        translation_manager.get_text('tab_geography')
    ])
    
    journal_names = list(journal_results.keys())
    
    with tab1:
        st.subheader(translation_manager.get_text('tab_main_metrics'))
        
        # Comparative metrics table
        comparative_data = []
        for journal_name in journal_names:
            result = journal_results[journal_name]
            analyzed_stats = result['analyzed_stats']
            enhanced_stats = result['enhanced_stats']
            
            row = {
                'Journal': journal_name,
                'Total Articles': analyzed_stats['n_items'],
                'H-index': enhanced_stats['h_index'],
                'Total Citations': enhanced_stats['total_citations'],
                'Avg Citations/Article': f"{enhanced_stats['avg_citations_per_article']:.1f}"
            }
            comparative_data.append(row)
        
        comparative_df = pd.DataFrame(comparative_data)
        st.dataframe(comparative_df)
        
        # Bar chart for H-index comparison
        h_indices = [journal_results[j]['enhanced_stats']['h_index'] for j in journal_names]
        fig = go.Figure(data=[
            go.Bar(name='H-index', x=journal_names, y=h_indices)
        ])
        fig.update_layout(title='H-index Comparison')
        st.plotly_chart(fig, use_container_width=True)
    
    with tab2:
        st.subheader(translation_manager.get_text('tab_authors_organizations'))
        
        # Comparative author metrics
        author_data = []
        for journal_name in journal_names:
            stats = journal_results[journal_name]['analyzed_stats']
            row = {
                'Journal': journal_name,
                'Avg Authors/Article': f"{stats['auth_mean']:.1f}",
                'Unique Affiliations': stats['unique_affiliations_count']
            }
            author_data.append(row)
        
        author_df = pd.DataFrame(author_data)
        st.dataframe(author_df)
        
        # Bar chart for average authors
        avg_authors = [journal_results[j]['analyzed_stats']['auth_mean'] for j in journal_names]
        fig = go.Figure(data=[
            go.Bar(name='Avg Authors', x=journal_names, y=avg_authors)
        ])
        fig.update_layout(title='Average Authors per Article Comparison')
        st.plotly_chart(fig, use_container_width=True)
    
    with tab3:
        st.subheader(translation_manager.get_text('tab_geography'))
        
        # Comparative geography metrics
        geo_data = []
        for journal_name in journal_names:
            stats = journal_results[journal_name]['analyzed_stats']
            row = {
                'Journal': journal_name,
                'International %': f"{stats['multi_country_pct']:.1f}%",
                'Unique Countries': stats['unique_countries_count']
            }
            geo_data.append(row)
        
        geo_df = pd.DataFrame(geo_data)
        st.dataframe(geo_df)
        
        # Bar chart for international collaboration
        int_coll = [journal_results[j]['analyzed_stats']['multi_country_pct'] for j in journal_names]
        fig = go.Figure(data=[
            go.Bar(name='International %', x=journal_names, y=int_coll)
        ])
        fig.update_layout(title='International Collaboration Comparison')
        st.plotly_chart(fig, use_container_width=True)

# === 19. Main Analysis Function ===
def analyze_journal(issns_list, period_str):
    global delayer
    delayer = AdaptiveDelayer()
    
    state = get_analysis_state()
    state.analysis_complete = False
    
    # Load metrics data at the start
    load_metrics_data()
    
    # Overall progress
    overall_progress = st.progress(0)
    overall_status = st.empty()
    
    # Period parsing
    overall_status.text(translation_manager.get_text('parsing_period'))
    
    years = parse_period(period_str)
    if not years:
        return {}
    from_date = f"{min(years)}-01-01"
    until_date = f"{max(years)}-12-31"
    
    overall_progress.progress(0.1)
    
    journal_results = {}
    
    for idx, issn in enumerate(issns_list):
        if not issn:
            continue
            
        overall_status.text(f"Processing journal {idx+1}/{len(issns_list)}: {issn}")
        
        # Journal name
        journal_name = get_journal_name(issn)
        st.success(translation_manager.get_text('journal_found').format(journal_name=journal_name, issn=issn))
        
        # Article retrieval
        items = fetch_articles_by_issn_period(issn, from_date, until_date)
        if not items:
            st.error(translation_manager.get_text('no_articles_found'))
            continue

        n_analyzed = len(items)
        st.success(translation_manager.get_text('articles_found').format(count=n_analyzed))
        
        # Data validation
        validated_items = validate_and_clean_data(items)
        journal_prefix = get_doi_prefix(validated_items[0].get('DOI', '')) if validated_items else ''
        
        # Analyzed articles processing
        analyzed_metadata = []
        dois = [item.get('DOI') for item in validated_items if item.get('DOI')]
        
        # Progress bar for metadata processing
        meta_progress = st.progress(0)
        meta_status = st.empty()
        
        # Prepare arguments for threading
        args_list = [(doi, state) for doi in dois]
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(get_unified_metadata, args): args for args in args_list}
            
            for i, future in enumerate(as_completed(futures)):
                args = futures[future]
                doi = args[0]
                try:
                    result = future.result()
                    analyzed_metadata.append({
                        'doi': doi,
                        'crossref': result['crossref'],
                        'openalex': result['openalex']
                    })
                except Exception as e:
                    st.error(f"Error processing DOI {doi}: {e}")
                
                progress = (i + 1) / len(dois)
                meta_progress.progress(progress)
                meta_status.text(f"{translation_manager.get_text('getting_metadata')}: {i + 1}/{len(dois)}")
        
        meta_progress.empty()
        meta_status.empty()
        
        # Citing works retrieval
        all_citing_metadata = []
        analyzed_dois = [am['doi'] for am in analyzed_metadata if am.get('doi')]
        
        # Progress bar for citation collection
        citing_progress = st.progress(0)
        citing_status = st.empty()
        
        # Prepare arguments for threading
        citing_args_list = [(doi, state) for doi in analyzed_dois]
        
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {executor.submit(get_citing_dois_and_metadata, args): args for args in citing_args_list}
            
            for i, future in enumerate(as_completed(futures)):
                args = futures[future]
                doi = args[0]
                try:
                    citings = future.result()
                    all_citing_metadata.extend(citings)
                except Exception as e:
                    st.error(f"Error collecting citations for {doi}: {e}")
                
                progress = (i + 1) / len(analyzed_dois)
                citing_progress.progress(progress)
                citing_status.text(f"{translation_manager.get_text('collecting_citations_progress')}: {i + 1}/{len(analyzed_dois)}")
        
        citing_progress.empty()
        citing_status.empty()
        
        # Unique citing works
        unique_citing_dois = set(c['doi'] for c in all_citing_metadata if c.get('doi'))
        n_citing = len(unique_citing_dois)
        st.success(translation_manager.get_text('unique_citing_works').format(count=n_citing))
        
        # Statistics calculation
        analyzed_stats = extract_stats_from_metadata(analyzed_metadata, journal_prefix=journal_prefix)
        citing_stats = extract_stats_from_metadata(all_citing_metadata, is_analyzed=False)
        enhanced_stats = enhanced_stats_calculation(analyzed_metadata, all_citing_metadata, state)
        
        # Overlap analysis
        overlap_details = analyze_overlaps(analyzed_metadata, all_citing_metadata, state)
        
        citation_timing = calculate_citation_timing(analyzed_metadata, state)
        
        # Fast metrics calculation (NEW)
        fast_metrics = calculate_all_fast_metrics(analyzed_metadata, all_citing_metadata, state, issn)
        
        # Store results for this journal
        journal_results[journal_name] = {
            'analyzed_stats': analyzed_stats,
            'citing_stats': citing_stats,
            'enhanced_stats': enhanced_stats,
            'citation_timing': citation_timing,
            'overlap_details': overlap_details,
            'fast_metrics': fast_metrics,
            'analyzed_metadata': analyzed_metadata,
            'all_citing_metadata': all_citing_metadata,
            'journal_name': journal_name,
            'issn': issn,
            'period': period_str,
            'n_analyzed': n_analyzed,
            'n_citing': n_citing
        }
        
        progress_per_journal = 0.9 / len(issns_list)
        overall_progress.progress(0.1 + (idx + 1) * progress_per_journal)
    
    # Report creation
    overall_status.text(translation_manager.get_text('creating_report'))
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f'journals_comparison_{timestamp}.xlsx'
    
    # Create Excel file in memory
    excel_buffer = io.BytesIO()
    create_enhanced_excel_report(journal_results, excel_buffer)
    
    excel_buffer.seek(0)
    state.excel_buffer = excel_buffer
    
    overall_progress.progress(1.0)
    overall_status.text(translation_manager.get_text('analysis_complete'))
    
    state.analysis_results = journal_results
    state.analysis_complete = True
    
    time.sleep(1)
    overall_progress.empty()
    overall_status.empty()
    
    return journal_results

def debug_issn_matching():
    """Debug function to check ISSN matching"""
    state = get_analysis_state()
    
    if state.cs_data is not None and not state.cs_data.empty:
        st.write("### 🔍 DEBUG: Scopus Data Sample")
        st.write("Columns:", state.cs_data.columns.tolist())
        st.write("First 5 rows:")
        st.dataframe(state.cs_data.head())
        
        # Check ISSN formats
        if 'Print ISSN' in state.cs_data.columns:
            st.write("### Print ISSN samples:")
            st.write(state.cs_data['Print ISSN'].head(10).tolist())
            st.write("Normalized versions:")
            normalized = state.cs_data['Print ISSN'].fillna('').astype(str).apply(normalize_issn_for_comparison)
            st.write(normalized.head(10).tolist())

# === 20. Main Interface ===
def main():
    initialize_analysis_state()
    state = get_analysis_state()
    
    # Language selector in sidebar
    with st.sidebar:
        st.header("🌍 Language")
        selected_language = st.selectbox(
            "Select language:",
            options=list(translation_manager.languages.keys()),
            format_func=lambda x: translation_manager.languages[x],
            index=0  # English by default
        )
        translation_manager.set_language(selected_language)
    
    # Header
    st.title("🔬 " + translation_manager.get_text('app_title'))
    st.markdown("---")
    
    # Sidebar with data input
    with st.sidebar:
        st.header("📝 " + translation_manager.get_text('analysis_parameters'))
        
        # Multiple ISSN input
        issns_input = st.text_input(
            "Enter 1-3 ISSNs (comma-separated):",
            value="2411-1414",
            help="e.g., 2411-1414 or 2411-1414,1234-5678,9876-5432"
        )
        
        period = st.text_input(
            translation_manager.get_text('analysis_period'),
            value="2022-2025",
            help=translation_manager.get_text('period_examples')
        )
        
        st.markdown("---")
        st.header("📚 " + translation_manager.get_text('dictionary_of_terms'))
        
        # Dictionary term search widget (simplified)
        search_term = st.selectbox(
            translation_manager.get_text('select_term_to_learn'),
            options=[""] + list(glossary.terms.keys()),
            format_func=lambda x: translation_manager.get_text('choose_term') if x == "" else x,
            help=translation_manager.get_text('study_metric_meanings')
        )
        
        if search_term:
            term_info = glossary.get_detailed_info(search_term)
            if term_info:
                st.info(f"**{term_info['term']}**\n\n{term_info['definition']}")
        
        st.markdown("---")
        st.header("💡 " + translation_manager.get_text('information'))
        
        st.info("**" + translation_manager.get_text('analysis_capabilities') + ":**\n" +
                "- " + translation_manager.get_text('capability_1') + "\n" +
                "- " + translation_manager.get_text('capability_2') + "\n" + 
                "- " + translation_manager.get_text('capability_3') + "\n" +
                "- " + translation_manager.get_text('capability_4') + "\n" +
                "- " + translation_manager.get_text('capability_5') + "\n" +
                "- " + translation_manager.get_text('capability_6') + "\n" +
                "- " + translation_manager.get_text('capability_7') + "\n" +
                "- " + translation_manager.get_text('capability_8'))
        
        st.warning("**" + translation_manager.get_text('note') + ":** \n" +
                  "- " + translation_manager.get_text('note_text_1') + "\n" +
                  "- " + translation_manager.get_text('note_text_2') + "\n" +
                  "- " + translation_manager.get_text('note_text_3') + "\n" +
                  "- " + translation_manager.get_text('note_text_4') + "\n" +
                  "- " + translation_manager.get_text('note_text_5'))
    
    # Main area
    col1, col2 = st.columns([2, 1])
    
    with col1:
        st.subheader("🚀 " + translation_manager.get_text('start_analysis'))
        
        if st.button(translation_manager.get_text('start_analysis'), type="primary", use_container_width=True):
            issns_str = issns_input.strip()
            if not issns_str:
                st.error("ISSN required")
                return
            
            issns_list = [issn.strip() for issn in issns_str.split(',') if issn.strip()]
            if len(issns_list) > 3 or len(issns_list) < 1:
                st.error("Enter 1-3 ISSNs")
                return
            
            if not period:
                st.error(translation_manager.get_text('period_required'))
                return
                
            with st.spinner(translation_manager.get_text('analysis_starting')):
                journal_results = analyze_journal(issns_list, period)
    
    with col2:
        st.subheader("📤 " + translation_manager.get_text('results'))
        
        if state.analysis_complete and state.excel_buffer is not None:
            results = state.analysis_results
            
            st.download_button(
                label="📥 " + translation_manager.get_text('download_excel_report'),
                data=state.excel_buffer,
                file_name=f"journals_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True
            )
    
    # Results display
    if state.analysis_complete:
        st.markdown("---")
        st.header("📊 " + translation_manager.get_text('analysis_results'))
        
        results = state.analysis_results
        
        # Summary information
        st.subheader("Summary")
        summary_data = []
        for journal_name, data in results.items():
            summary_data.append({
                'Journal': journal_name,
                'Articles Analyzed': data['n_analyzed'],
                'Citing Works': data['n_citing']
            })
        summary_df = pd.DataFrame(summary_data)
        st.dataframe(summary_df)
        
        # Visualizations (comparative)
        create_visualizations(results)
        
        # Detailed statistics (simplified comparative)
        st.markdown("---")
        st.header("📈 " + translation_manager.get_text('detailed_statistics'))
        
        tab1, tab2, tab3 = st.tabs([
            translation_manager.get_text('analyzed_articles'), 
            translation_manager.get_text('citing_works'), 
            translation_manager.get_text('comparative_analysis')
        ])
        
        with tab1:
            st.subheader(translation_manager.get_text('analyzed_articles_statistics'))
            analyzed_data = []
            for journal_name, data in results.items():
                stats = data['analyzed_stats']
                row = {
                    'Journal': journal_name,
                    'Total Articles': stats['n_items'],
                    'Total References': stats['total_refs'],
                    'Self-Citations %': f"{stats['self_cites_pct']:.1f}%",
                    'International %': f"{stats['multi_country_pct']:.1f}%"
                }
                analyzed_data.append(row)
            analyzed_df = pd.DataFrame(analyzed_data)
            st.dataframe(analyzed_df)
        
        with tab2:
            st.subheader(translation_manager.get_text('citing_works_statistics'))
            citing_data = []
            for journal_name, data in results.items():
                stats = data['citing_stats']
                row = {
                    'Journal': journal_name,
                    'Total Citing Articles': stats['n_items'],
                    'Unique Journals': stats['unique_journals_count'],
                    'Unique Publishers': stats['unique_publishers_count']
                }
                citing_data.append(row)
            citing_df = pd.DataFrame(citing_data)
            st.dataframe(citing_df)
        
        with tab3:
            st.subheader(translation_manager.get_text('comparative_analysis'))
            comp_data = []
            for journal_name, data in results.items():
                analyzed_stats = data['analyzed_stats']
                enhanced_stats = data['enhanced_stats']
                row = {
                    'Journal': journal_name,
                    'Avg Authors (Analyzed)': f"{analyzed_stats['auth_mean']:.1f}",
                    'Avg References (Analyzed)': f"{analyzed_stats['ref_mean']:.1f}",
                    'Avg Authors (Citing)': f"{data['citing_stats']['auth_mean']:.1f}",
                    'Avg References (Citing)': f"{data['citing_stats']['ref_mean']:.1f}"
                }
                comp_data.append(row)
            comp_df = pd.DataFrame(comp_data)
            st.dataframe(comp_df)

# Run application
if __name__ == "__main__":
    main()
