import time
from playwright.sync_api import sync_playwright

# Wait for server to start
time.sleep(2)

try:
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            page.goto('http://localhost:8000')
            
            # Get the HTML content
            html = page.content()
            
            print("Dashboard loaded successfully!")
            print("\n--- Page Content Preview ---")
            for i, line in enumerate(html.split('\n')[:30]):
                print(line)
            
            if "Internal Server Error" in html:
                print("\n⚠️ WARNING: Internal Server Error found!")
            else:
                print("\n✓ No Internal Server Error - Dashboard is working!")
                
        except Exception as e:
            print(f"Error accessing dashboard: {e}")
        
        browser.close()
except ImportError as e:
    print("Playwright not installed:", e)
except Exception as e:
    print("Error during test:", e)
