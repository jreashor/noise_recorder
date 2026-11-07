from playwright.sync_api import sync_playwright
import time

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True)
    page = browser.new_page()
    
    try:
        # Check response via exception or try/catch
        page.goto('http://localhost:8000')
        
        print("Page loaded!")
        
        # Get full HTML
        html = page.content()
        
        # Find error messages
        
    except Exception as e:
        print(f"Error: {e}")
        page.screenshot(path='error_page.png')
        html = page.content()
        
        # Find error messages
        if "Internal Server Error" in html:
            print("\n⚠️ INTERNAL SERVER ERROR DETECTED")
            
        if "500" in html:
            print("HTTP 500 found in page")
            
        # Print relevant parts
        if "error" in html.lower() or "Error" in html:
            lines = html.split('\n')
            for i, line in enumerate(lines):
                if 'error' in line.lower() or '<p>' in line.lower():
                    print(f"\nLine {i}: {line}")
        
        # Try to get JSON data that might be embedded
        if "events:" in html and "minutes:" in html:
            import json
            # Extract the data portion
            start_idx = html.find('events:')
            end_idx = html.find('\n', start_idx)
            if start_idx != -1 and end_idx != -1:
                data_str = html[start_idx:end_idx]
                print("\nData extracted successfully:", data_str[:200])
        
        page.screenshot(path='dashboard_full_page.png')
        
    except Exception as e:
        print(f"Error navigating: {e}")
    
    browser.close()
