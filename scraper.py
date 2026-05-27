import os
import sys
import json
import time
import random
import logging
import asyncio
from datetime import datetime, timezone
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ==========================================
# CONFIGURATION & DIRECTORIES
# ==========================================
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "data")
LOGS_DIR = os.path.join(SCRIPT_DIR, "logs")
SCREENSHOTS_DIR = os.path.join(SCRIPT_DIR, "screenshots")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

# File Paths
MODULES_JSON_PATH = os.path.join(DATA_DIR, "modules.json")
PROGRESS_JSON_PATH = os.path.join(SCRIPT_DIR, "progress.json")
LOG_FILE_PATH = os.path.join(LOGS_DIR, "scraper.log")

# Setup Logging
logger = logging.getLogger("MSLearnCollector")
logger.setLevel(logging.INFO)

# File Handler
file_handler = logging.FileHandler(LOG_FILE_PATH, encoding="utf-8")
file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(file_handler)

# Console Handler
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(console_handler)

# Scraper Parameters
BASE_URL = "https://learn.microsoft.com/en-us/training/browse/"
CARDS_PER_PAGE = 30
MAX_RETRIES = 3
DELAY_RANGE = (1.5, 3.0)  # Human-like delay range between actions

# ==========================================
# HELPER FUNCTIONS
# ==========================================
def load_existing_data():
    """Loads already scraped modules to populate seen set and output list."""
    seen = set()
    items = []
    if os.path.exists(MODULES_JSON_PATH):
        try:
            with open(MODULES_JSON_PATH, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    items = json.loads(content)
                    for item in items:
                        name = item.get("name", "").strip()
                        if name:
                            seen.add(name.lower())
            logger.info(f"Loaded {len(items)} existing items from modules.json for deduplication.")
        except Exception as e:
            logger.error(f"Error loading modules.json: {e}. Starting fresh.")
    return seen, items

def load_progress():
    """Loads scraping progress from progress.json."""
    if os.path.exists(PROGRESS_JSON_PATH):
        try:
            with open(PROGRESS_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                current_page = data.get("current_page", 1)
                scraped_count = data.get("scraped_count", 0)
                logger.info(f"Resuming from progress.json: page {current_page}, scraped count {scraped_count}.")
                return current_page, scraped_count
        except Exception as e:
            logger.error(f"Error loading progress.json: {e}. Starting from page 1.")
    return 1, 0

def save_progress(current_page, scraped_count, total_results=None):
    """Saves scraping progress to progress.json."""
    data = {
        "current_page": current_page,
        "scraped_count": scraped_count,
        "total_results_estimate": total_results,
        "last_updated": datetime.now(timezone.utc).isoformat()
    }
    try:
        with open(PROGRESS_JSON_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        logger.debug(f"Progress saved: page {current_page}.")
    except Exception as e:
        logger.error(f"Failed to save progress.json: {e}")

def save_data(items):
    """Saves the accumulated items to modules.json."""
    try:
        # Atomic write by writing to a temp file and renaming it
        temp_path = MODULES_JSON_PATH + ".tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=2, ensure_ascii=False)
        if os.path.exists(MODULES_JSON_PATH):
            os.remove(MODULES_JSON_PATH)
        os.rename(temp_path, MODULES_JSON_PATH)
    except Exception as e:
        logger.error(f"Failed to save data to modules.json: {e}")

def normalize_string(s):
    """Removes extra whitespaces and standardizes casing."""
    if not s:
        return ""
    return " ".join(s.strip().split())

# ==========================================
# SCRAPER CORE LOGIC
# ==========================================
async def scrape_page_cards(page, seen, items):
    """Extracts all card titles and types from the current page."""
    # Wait for the card articles to load
    await page.wait_for_selector("article[data-bi-name='card']", timeout=15000)
    
    # Query all card containers
    cards = await page.locator("article[data-bi-name='card']").all()
    
    new_items_count = 0
    page_items = []
    
    for card in cards:
        try:
            # Extract card supertitle (Type: e.g. MODULE, LEARNING PATH)
            supertitle_el = card.locator(".card-supertitle")
            card_type = ""
            if await supertitle_el.count() > 0:
                card_type = await supertitle_el.first.text_content()
                card_type = normalize_string(card_type).lower()
            
            # Extract card title (Name)
            title_el = card.locator(".card-title")
            card_name = ""
            if await title_el.count() > 0:
                card_name = await title_el.first.text_content()
                card_name = normalize_string(card_name)
            
            if not card_name:
                continue
                
            # Add to list if unique
            key = card_name.lower()
            if key not in seen:
                seen.add(key)
                item = {
                    "name": card_name,
                    "type": card_type if card_type else "module" # Default fallback
                }
                items.append(item)
                page_items.append(item)
                new_items_count += 1
        except Exception as e:
            logger.debug(f"Skipping a card due to extraction error: {e}")
            continue
            
    return new_items_count, page_items

async def get_total_results_count(page):
    """Extracts the 'X results' count from the top of the search grid."""
    try:
        # Check elements that usually contain results count
        # E.g. "4,613 results"
        locators = [
            "span.search-results-count", 
            "div.search-results-count", 
            "h2.search-results-count",
            ".results-count"
        ]
        for loc in locators:
            el = page.locator(loc)
            if await el.count() > 0 and await el.first.is_visible():
                text = await el.first.text_content()
                if text:
                    text_clean = normalize_string(text).lower()
                    if "result" in text_clean:
                        # Extract digit
                        digits = "".join(c for c in text_clean if c.isdigit() or c == ",")
                        return int(digits.replace(",", ""))
        
        # Fallback evaluation
        count = await page.evaluate("""() => {
            const el = Array.from(document.querySelectorAll('div, span, h1, h2, p')).find(e => 
                e.innerText && /\\d{1,3}(,\\d{3})*\\s+results/i.test(e.innerText)
            );
            if (el) {
                const match = el.innerText.match(/(\\d{1,3}(,\\d{3})*)\\s+results/i);
                return match ? parseInt(match[1].replace(/,/g, '')) : null;
            }
            return null;
        }""")
        if count:
            return count
    except Exception as e:
        logger.debug(f"Could not extract total results count: {e}")
    return None

async def run_scraper(headed=False):
    # Load state
    seen, items = load_existing_data()
    current_page, scraped_count = load_progress()
    
    logger.info("==================================================")
    logger.info("      STARTING MICROSOFT LEARN COLLECTOR         ")
    logger.info("==================================================")
    
    async with async_playwright() as p:
        # Launch browser (with anti-detection arguments)
        browser = await p.chromium.launch(
            headless=not headed,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized"
            ]
        )
        
        # Create standard desktop context
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        
        page = await context.new_page()
        
        # Initial navigation url based on resumption state
        target_url = BASE_URL
        if current_page > 1:
            skip_val = (current_page - 1) * CARDS_PER_PAGE
            target_url = f"{BASE_URL}?skip={skip_val}"
            logger.info(f"Resuming by loading URL directly: {target_url}")
        else:
            logger.info(f"Starting crawl from page 1 URL: {target_url}")
            
        # Initial Page Load with Retry
        success = False
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(f"Loading page URL (Attempt {attempt}/{MAX_RETRIES})...")
                await page.goto(target_url, timeout=45000, wait_until="domcontentloaded")
                # Extra small delay for dynamic content
                await page.wait_for_timeout(3000)
                success = True
                break
            except Exception as e:
                logger.warning(f"Failed to load page URL on attempt {attempt}: {e}")
                if attempt == MAX_RETRIES:
                    screenshot_path = os.path.join(SCREENSHOTS_DIR, f"error_init_load_{int(time.time())}.png")
                    await page.screenshot(path=screenshot_path)
                    logger.error(f"Critical error loading initial page. Screenshot saved to {screenshot_path}. Exiting.")
                    await browser.close()
                    return
                await asyncio.sleep(5)
                
        # Main extraction loop
        total_results = None
        consecutive_empty_pages = 0
        
        while True:
            logger.info(f"--- Scraping Page {current_page} ---")
            
            # 1. Fetch total results count on page 1 or if not already set
            if total_results is None:
                total_results = await get_total_results_count(page)
                if total_results:
                    logger.info(f"Target total dataset size reported by Microsoft Learn: {total_results} items.")
            
            # 2. Extract cards from current page
            page_success = False
            page_new_count = 0
            page_extracted_items = []
            
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    page_new_count, page_extracted_items = await scrape_page_cards(page, seen, items)
                    page_success = True
                    break
                except Exception as e:
                    logger.warning(f"Error scraping cards on Page {current_page} (Attempt {attempt}/{MAX_RETRIES}): {e}")
                    if attempt == MAX_RETRIES:
                        screenshot_path = os.path.join(SCREENSHOTS_DIR, f"error_scrape_page_{current_page}_{int(time.time())}.png")
                        await page.screenshot(path=screenshot_path)
                        logger.error(f"Saved failure screenshot to {screenshot_path}.")
                    await asyncio.sleep(3)
            
            if not page_success:
                logger.error(f"Skipping scraping for page {current_page} after multiple failures.")
                # We can either increment page and continue, or exit. Let's increment and continue
                current_page += 1
                continue
                
            # Log results of this page
            total_on_page = len(page_extracted_items)
            logger.info(f"Page {current_page} processed. Found {total_on_page} cards. {page_new_count} were new items.")
            
            # If we find 0 items on a page, track it to prevent infinite loops
            if total_on_page == 0:
                consecutive_empty_pages += 1
                if consecutive_empty_pages >= 3:
                    logger.warning("Scraped 0 cards for 3 consecutive pages. Reached the end of available dataset.")
                    break
            else:
                consecutive_empty_pages = 0
                
            # 3. Save progress and data
            scraped_count = len(items)
            save_data(items)
            save_progress(current_page, scraped_count, total_results)
            
            # Log current running totals
            if total_results:
                percent = (scraped_count / total_results) * 100
                logger.info(f"Progress: {scraped_count}/{total_results} items collected ({percent:.2f}%).")
            else:
                logger.info(f"Progress: {scraped_count} items collected.")
                
            # 4. Check for Next button pagination
            next_btn = page.locator("nav[aria-label='pagination'] button[aria-label='Next']")
            
            # Determine if we should stop
            next_visible = await next_btn.is_visible()
            next_disabled = False
            if next_visible:
                # Check for disabled state (either disabled attribute or aria-disabled="true")
                is_disabled_attr = await next_btn.get_attribute("disabled") is not None
                is_aria_disabled = await next_btn.get_attribute("aria-disabled") == "true"
                next_disabled = is_disabled_attr or is_aria_disabled
                
            if not next_visible or next_disabled:
                logger.info("Pagination Next button is disabled or not visible. End of list reached.")
                break
                
            # 5. Navigate to Next page by clicking the button
            logger.info("Navigating to next page...")
            active_before = await page.evaluate("""() => {
                const active = document.querySelector("nav[aria-label='pagination'] button.is-current");
                return active ? active.innerText.strip || active.textContent.strip || active.innerText : '';
            }""")
            
            click_success = False
            for click_attempt in range(1, MAX_RETRIES + 1):
                try:
                    # Scroll button into view and click
                    await next_btn.scroll_into_view_if_needed()
                    await next_btn.click(timeout=10000)
                    click_success = True
                    break
                except Exception as e:
                    logger.warning(f"Failed to click Next button on attempt {click_attempt}: {e}")
                    await asyncio.sleep(2)
            
            if not click_success:
                logger.error("Could not click Next button. Trying to force skip-based URL load as fallback.")
                current_page += 1
                skip_val = (current_page - 1) * CARDS_PER_PAGE
                await page.goto(f"{BASE_URL}?skip={skip_val}", timeout=30000)
                await page.wait_for_timeout(3000)
                continue
                
            # Wait for the next page to load by waiting for active page index to update
            page_update_success = False
            for wait_attempt in range(15):
                await page.wait_for_timeout(1000)
                active_after = await page.evaluate("""() => {
                    const active = document.querySelector("nav[aria-label='pagination'] button.is-current");
                    return active ? active.innerText.strip || active.textContent.strip || active.innerText : '';
                }""")
                if active_after and active_after != active_before:
                    page_update_success = True
                    logger.debug(f"Successfully loaded next page index: {active_after}")
                    break
            
            if not page_update_success:
                logger.warning("Pagination index did not update. Doing a URL check...")
                # Verify if the URL itself has changed or wait standard timeout
                await page.wait_for_timeout(2000)
            
            # Anti-detection delay between pages
            delay = random.uniform(*DELAY_RANGE)
            logger.debug(f"Sleeping for {delay:.2f}s...")
            await asyncio.sleep(delay)
            
            current_page += 1
            
        logger.info("==================================================")
        logger.info("             COLLECTION COMPLETED!                ")
        logger.info(f"Total Unique Items Collected: {len(items)}")
        logger.info("==================================================")
        
        # Clean progress on completion
        if os.path.exists(PROGRESS_JSON_PATH):
            os.remove(PROGRESS_JSON_PATH)
            logger.info("Cleaned up progress.json since scrape completed successfully.")
            
        await browser.close()

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Microsoft Learn Browse Page Dataset Collector")
    parser.add_argument("--headed", action="store_true", help="Run browser in headed mode (visible window)")
    args = parser.parse_args()
    
    try:
        asyncio.run(run_scraper(headed=args.headed))
    except KeyboardInterrupt:
        logger.info("\nScraper interrupted by user (Ctrl+C). Gracefully saving progress...")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"Unhandled exception in scraper execution: {e}", exc_info=True)
        sys.exit(1)


