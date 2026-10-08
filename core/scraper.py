import re
from urllib.parse import urljoin
from collections import OrderedDict
from bs4 import BeautifulSoup

from core.utils import sanitize_filename


def extract_clean_title(a_tag) -> str:
    """
    Extracts the clean activity title without Moodle accessibility tags (e.g. 'קובץ' or 'Assignment').
    """
    instance_span = a_tag.find(class_='instancename')
    if instance_span:
        for hide in instance_span.find_all(class_=re.compile(r'accesshide|sr-only')):
            hide.decompose()
        title = instance_span.get_text(strip=True)
    else:
        title = a_tag.get_text(strip=True)

    title = re.sub(r'(קובץ|File|תיקייה|Folder|מטלה|Assignment|דף|Page|קישור|URL)\s*$', '', title, flags=re.IGNORECASE).strip()
    return title or "Activity"


def find_downloadable_files_in_page(page_soup: BeautifulSoup, base_page_url: str) -> list[str]:
    """
    Scans a Moodle sub-page (Assignment, Page, Resource) for all downloadable file links.
    """
    found_urls = []
    seen = set()

    file_re = re.compile(r'pluginfile\.php|draftfile\.php|\.(pdf|docx?|pptx?|xlsx?|zip|rar|7z|py|c|cpp|txt|tar|gz|mat|m)(\?|$)', re.I)

    # 1. <a> tags
    for a in page_soup.find_all('a', href=file_re):
        raw_href = a.get('href', '')
        if raw_href and not raw_href.startswith('javascript:'):
            full = urljoin(base_page_url, raw_href)
            if full not in seen:
                seen.add(full)
                found_urls.append(full)

    # 2. <iframe> / <embed> / <object>
    for tag in page_soup.find_all(['iframe', 'embed'], src=file_re):
        src = tag.get('src', '')
        if src:
            full = urljoin(base_page_url, src)
            if full not in seen:
                seen.add(full)
                found_urls.append(full)

    for tag in page_soup.find_all('object', data=file_re):
        data_url = tag.get('data', '')
        if data_url:
            full = urljoin(base_page_url, data_url)
            if full not in seen:
                seen.add(full)
                found_urls.append(full)

    return found_urls


def parse_course_activities(soup: BeautifulSoup, course_url: str, include_nested: bool = True) -> OrderedDict:
    """
    Finds all activity links matching mod regex, groups them by course sections/topics while preserving page order.
    Returns an OrderedDict mapping section names to lists of item dicts.
    """
    if include_nested:
        mod_regex = re.compile(r'/mod/(resource|folder|assign|page|url|h5pactivity)/view\.php\?id=\d+')
    else:
        mod_regex = re.compile(r'/mod/(resource|folder)/view\.php\?id=\d+')

    all_activity_links = soup.find_all('a', href=mod_regex)
    grouped_links = OrderedDict()

    for a in all_activity_links:
        raw_href = a['href']
        href = urljoin(course_url, raw_href)
        activity_title = extract_clean_title(a)

        mod_match = re.search(r'/mod/(\w+)/', href)
        mod_type = mod_match.group(1) if mod_match else 'resource'

        section_name = "General"
        parent_section = a.find_parent(
            ['li', 'div', 'section'],
            class_=lambda c: c and ('course-section' in c or ('section' in c and 'main' in c) or 'section-item' in c)
        )

        if parent_section:
            heading = parent_section.find(['h2', 'h3', 'h4', 'h5', 'span'], class_=re.compile(r'sectionname|title|name|section-title'))
            if heading:
                section_name = heading.get_text(strip=True)
            else:
                aria_label = parent_section.get('aria-label')
                if aria_label:
                    section_name = aria_label

        safe_section_name = sanitize_filename(section_name)
        if not safe_section_name:
            safe_section_name = "General"

        if safe_section_name not in grouped_links:
            grouped_links[safe_section_name] = []

        if not any(item['href'] == href for item in grouped_links[safe_section_name]):
            grouped_links[safe_section_name].append({
                'href': href,
                'title': activity_title,
                'mod_type': mod_type
            })

    return grouped_links

