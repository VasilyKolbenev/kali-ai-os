import sys
import argparse
import urllib.request
import urllib.parse
import json
from html.parser import HTMLParser

class TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.in_script_or_style = False

    def handle_starttag(self, tag, attrs):
        if tag in ['script', 'style', 'noscript']:
            self.in_script_or_style = True

    def handle_endtag(self, tag):
        if tag in ['script', 'style', 'noscript']:
            self.in_script_or_style = False

    def handle_data(self, data):
        if not self.in_script_or_style:
            clean = data.strip()
            if clean:
                self.text.append(clean)

def fetch_url(url: str) -> str:
    req = urllib.request.Request(
        url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            extractor = TextExtractor()
            extractor.feed(html)
            text = " ".join(extractor.text)
            # Limit to ~4000 chars to avoid overloading LLM context
            if len(text) > 4000:
                text = text[:4000] + "... [TRUNCATED]"
            return text
    except Exception as e:
        return f"Error fetching URL: {str(e)}"

def search_duckduckgo(query: str) -> str:
    # DuckDuckGo Lite HTML version
    encoded_query = urllib.parse.quote_plus(query)
    url = f"https://lite.duckduckgo.com/lite/"
    data = urllib.parse.urlencode({'q': query}).encode('utf-8')
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Content-Type': 'application/x-www-form-urlencoded'
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            # Very basic extraction: DDG lite has result snippets
            extractor = TextExtractor()
            extractor.feed(html)
            text = " ".join(extractor.text)
            # Find where results start
            if "Web Results" in text:
                text = text[text.find("Web Results"):]
            if len(text) > 4000:
                text = text[:4000] + "... [TRUNCATED]"
            return text
    except Exception as e:
        return f"Error searching: {str(e)}"

def main():
    parser = argparse.ArgumentParser(description="Web Surfer Agent Tool")
    parser.add_argument("--url", type=str, help="Fetch and extract text from a specific URL")
    parser.add_argument("--search", type=str, help="Search the web and return snippets")
    
    args = parser.parse_args()
    
    result = {}
    if args.url:
        result["url"] = args.url
        result["content"] = fetch_url(args.url)
    elif args.search:
        result["query"] = args.search
        result["results"] = search_duckduckgo(args.search)
    else:
        result["error"] = "Must provide --url or --search"
        
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
