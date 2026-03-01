import os
import argparse
import requests
from bs4 import BeautifulSoup
import re
from urllib.parse import unquote

def get_filename_from_cd(cd):
    """
    Extracts the filename from the Content-Disposition header.
    """
    if not cd:
        return None
    
    # Check for filename="..."
    fname = re.findall(r'filename="([^"]+)"', cd)
    if not fname:
        # Check for filename=...
        fname = re.findall(r'filename=([^;]+)', cd)
    if not fname:
        # Check for filename*=UTF-8''...
        fname = re.findall(r"filename\*[=A-Za-z0-9\-]*'[A-Za-z0-9\-]*'([^;]+)", cd)
        
    if not fname:
        return None
        
    # Clean up encoding if present (e.g. utf-8''filename)
    clean_fname = fname[0].strip()
    
    # Fix Moodle's UTF-8 filenames sent as raw bytes over HTTP headers
    try:
        clean_fname = clean_fname.encode('latin1').decode('utf-8')
    except Exception:
        pass
        
    return unquote(clean_fname)

def main():
    print("=== Moodle Course Downloader ===")
    print("This script will download all resources and folders from a Moodle course.")
    print("-" * 80)
    print()
    print("STEP 1: MOODLE COURSE URL")
    print("Please paste the full URL of your Moodle course page.")
    print("Example: https://moodle.ruppin.ac.il/course/view.php?id=1234")
    print()
    
    course_url = input("Enter the full Moodle course URL: ").strip()
    while not course_url:
        print("Please enter a valid URL.")
        course_url = input("Enter the full Moodle course URL: ").strip()
    
    # Extract ID from URL
    match = re.search(r'id=(\d+)', course_url)
    course_id = match.group(1) if match else ""

    if course_id:
        print(f"\n[?] Extracted Course ID: {course_id}")
        confirm = input("Press ENTER to confirm, or type the correct ID: ").strip()
        
        if confirm:
            course_id = confirm
            
    if not course_id:
        course_id = input("\nCould not extract ID automatically. Please enter the numeric Course ID: ").strip()

    if not course_id.isdigit():
        print("Error: Course ID must be numeric.")
        return
        
    # Reconstruct the course URL just in case the ID was manually changed
    base_url = course_url.split('?')[0] if '?' in course_url else course_url
    course_url = f"{base_url}?id={course_id}"
    
    print(f"\n[OK] Using Course ID: {course_id}")
    print()
    print("STEP 2: GET YOUR LOGIN COOKIE")
    print("To download files, this script needs your active Moodle login.")
    print("  1. Log into your Moodle in a web browser.")
    print("  2. Press F12 to open Developer Tools.")
    print("  3. Go to the Application tab (or Storage in Firefox).")
    print("  4. Click on 'Cookies' on the left side.")
    print("  5. Find the row named 'MoodleSession' and copy its exact Value.")
    print("     (Example: 6ir67p4doaf4pb0gb4oavl6puq)")
    print()
    
    moodle_cookie = input("Paste your MoodleSession cookie value: ").strip()
    while not moodle_cookie:
        print("The cookie cannot be empty. We need it to bypass the login screen.")
        moodle_cookie = input("Paste your MoodleSession cookie value: ").strip()

    cookies = {"MoodleSession": moodle_cookie}
    
    download_dir = f"moodle_course_{course_id}"
    os.makedirs(download_dir, exist_ok=True)
    print(f"\nFiles will be saved to: {os.path.abspath(download_dir)}")
    
    print(f"Accessing {course_url} ...")
    
    try:
        response = requests.get(course_url, cookies=cookies)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Failed to access course: {e}")
        return
        
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Check if we were redirected to login
    if "login" in response.url.lower() or soup.find('form', action=re.compile("login", re.I)):
        print("\n[!] ERROR: Authentication failed.")
        print("Your MoodleSession cookie might be invalid, expired, or incorrect.")
        print("Please log into Moodle in your browser, and copy the fresh 'MoodleSession' cookie.")
        return

    def clean_dirname(name):
        return re.sub(r'[\\/*?:"<>|]', "", name).strip()

    # Find all resource and folder links anywhere on the page
    all_links = soup.find_all('a', href=re.compile(r'/mod/(resource|folder)/view\.php\?id='))
    
    if not all_links:
        print("Could not find any downloadable resources or folders in this course.")
        print("Make sure you are enrolled, the course has files, and the ID is correct.")
        return

    print(f"Found {len(all_links)} downloadable items.")
    
    # We will group them by their closest section heading
    grouped_links = {}
    
    for a in all_links:
        href = a['href']
        
        # Determine section name
        section_name = "General"
        
        # In Moodle 4, topics are usually in <li class="section course-section ...">
        # In Moodle 3, they are in <li class="section main ...">
        # Let's find a parent that looks like a high-level course section container.
        parent_section = a.find_parent(['li', 'div', 'section'], class_=lambda c: c and ('course-section' in c or ('section' in c and 'main' in c)))
        
        if parent_section:
            # Look for heading inside or near this section
            heading = parent_section.find(['h3', 'h4', 'h2'], class_=re.compile(r'sectionname|title|name'))
            if heading:
                section_name = heading.get_text(strip=True)
            else:
                aria_label = parent_section.get('aria-label')
                if aria_label:
                    section_name = aria_label


        safe_section_name = clean_dirname(section_name)
        if not safe_section_name:
            safe_section_name = "General"
            
        if safe_section_name not in grouped_links:
            grouped_links[safe_section_name] = set()
            
        grouped_links[safe_section_name].add(href)
        
    for safe_section_name, links in grouped_links.items():
        print(f"\n--- Processing '{safe_section_name}' ({len(links)} items) ---")
        section_dir = os.path.join(download_dir, safe_section_name)
        os.makedirs(section_dir, exist_ok=True)

    
        for link in links:
            try:
                print(f"Evaluating link: {link}")
                res = requests.get(link, cookies=cookies, allow_redirects=True)
                
                # 1. Check if direct file download (e.g. forcedownload)
                cd = res.headers.get('Content-Disposition')
                if cd and 'filename' in cd:
                    filename = get_filename_from_cd(cd) or "unnamed_file"
                    filepath = os.path.join(section_dir, filename)
                    with open(filepath, 'wb') as f:
                        f.write(res.content)
                    print(f"   [+] Downloaded direct file: {filename}")
                    continue
                    
                # If not direct file, parse the resource page
                page_soup = BeautifulSoup(res.content, 'html.parser')
                
                # 2. Check for "Download folder" button
                folder_form = page_soup.find('form', action=re.compile('folder/download_folder.php'))
                if folder_form:
                    action = folder_form['action']
                    data = {inp.get('name'): inp.get('value') for inp in folder_form.find_all('input') if inp.get('name')}
                    
                    print("   [*] Found folder. Downloading ZIP archive...")
                    folder_res = requests.post(action, data=data, cookies=cookies)
                    
                    folder_cd = folder_res.headers.get('Content-Disposition')
                    filename = get_filename_from_cd(folder_cd) if folder_cd else f"folder_{link.split('=')[-1]}.zip"
                    filepath = os.path.join(section_dir, filename)
                    
                    with open(filepath, 'wb') as f:
                        f.write(folder_res.content)
                    print(f"   [+] Downloaded folder: {filename}")
                    continue
                    
                # 3. Check for embedded file links inside resource page (pluginfile.php)
                file_links = page_soup.find_all('a', href=re.compile(r'pluginfile\.php'))
                downloaded_something = False
                for a in file_links:
                    file_url = a['href']
                    
                    # Ensure forcedownload is added to bypass viewer
                    if '?forcedownload=1' not in file_url and '&forcedownload=1' not in file_url:
                        file_url += "&forcedownload=1" if '?' in file_url else "?forcedownload=1"
                    
                    file_res = requests.get(file_url, cookies=cookies)
                    file_cd = file_res.headers.get('Content-Disposition')
                    
                    if file_cd and 'filename' in file_cd:
                        filename = get_filename_from_cd(file_cd)
                        if not filename:
                            filename = unquote(file_url.split('?')[0].split('/')[-1])
                        filepath = os.path.join(section_dir, filename)
                        
                        with open(filepath, 'wb') as f:
                            f.write(file_res.content)
                        print(f"   [+] Downloaded embedded file: {filename}")
                        downloaded_something = True
                        
                if not downloaded_something:
                    print("   [-] Did not find any downloadable content at this link.")

            except Exception as e:
                print(f"   [!] Error processing {link}: {e}")

    print(f"\nDone! All files have been downloaded to the '{download_dir}' directory.")

if __name__ == "__main__":
    main()
