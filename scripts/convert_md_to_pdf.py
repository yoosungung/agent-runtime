import os
import re
import html
import sys
from pathlib import Path

# Create a beautiful HTML wrapper with styling and mermaid support
HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{title}</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Nanum+Gothic:wght@400;700&family=JetBrains+Mono&display=swap');

        body {{
            font-family: 'Nanum Gothic', 'Inter', sans-serif;
            line-height: 1.6;
            color: #24292e;
            max-width: 900px;
            margin: 0 auto;
            padding: 40px;
            background-color: #fff;
        }}

        h1, h2, h3, h4, h5, h6 {{
            font-family: 'Inter', 'Nanum Gothic', sans-serif;
            color: #111;
            margin-top: 1.5em;
            margin-bottom: 0.5em;
            font-weight: 600;
        }}

        h1 {{
            font-size: 2.2em;
            border-bottom: 2px solid #eaecef;
            padding-bottom: 0.3em;
        }}

        h2 {{
            font-size: 1.6em;
            border-bottom: 1px solid #eaecef;
            padding-bottom: 0.3em;
            margin-top: 2em;
        }}

        h3 {{
            font-size: 1.3em;
        }}

        a {{
            color: #0366d6;
            text-decoration: none;
        }}

        a:hover {{
            text-decoration: underline;
        }}

        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 20px 0;
        }}

        th, td {{
            border: 1px solid #dfe2e5;
            padding: 10px 12px;
            text-align: left;
        }}

        th {{
            background-color: #f6f8fa;
            font-weight: bold;
        }}

        tr:nth-child(even) {{
            background-color: #f9f9f9;
        }}

        code {{
            font-family: 'JetBrains Mono', 'Courier New', monospace;
            background-color: rgba(27,31,35,0.05);
            padding: 0.2em 0.4em;
            border-radius: 3px;
            font-size: 85%;
        }}

        pre {{
            background-color: #f6f8fa;
            border-radius: 6px;
            padding: 16px;
            overflow: auto;
        }}

        pre code {{
            background-color: transparent;
            padding: 0;
            border-radius: 0;
            font-size: 90%;
            color: #24292e;
        }}

        img {{
            max-width: 100%;
            height: auto;
            display: block;
            margin: 25px auto;
            border-radius: 6px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }}

        blockquote {{
            border-left: 4px solid #dfe2e5;
            color: #6a737d;
            padding: 0 1em;
            margin: 20px 0;
        }}

        hr {{
            height: 0.25em;
            padding: 0;
            margin: 24px 0;
            background-color: #e1e4e8;
            border: 0;
        }}

        /* Page breaks and margins for PDF printing */
        @media print {{
            body {{
                padding: 0;
                max-width: 100%;
            }}
            h1, h2, h3 {{
                page-break-after: avoid;
            }}
            pre, blockquote, table, img, .mermaid {{
                page-break-inside: avoid;
            }}
            @page {{
                margin: 20mm;
            }}
        }}

        /* Mermaid style wrapper */
        .mermaid {{
            display: flex;
            justify-content: center;
            margin: 30px 0;
            background: #fdfdfd;
            padding: 20px;
            border: 1px solid #eee;
            border-radius: 8px;
        }}
    </style>
    <!-- Include Mermaid.js from CDN -->
    <script type="module">
        import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.esm.min.mjs';
        mermaid.initialize({{
            startOnLoad: true,
            theme: 'default',
            flowchart: {{
                useWidth: true,
                htmlLabels: true
            }}
        }});
    </script>
</head>
<body>
    {content}
</body>
</html>
"""

def convert_md_to_html(md_path, html_path):
    import markdown
    
    print(f"Reading {md_path}...")
    with open(md_path, "r", encoding="utf-8") as f:
        text = f.read()
    
    # Parse Markdown to HTML with 'extra' extension for tables & code blocks
    html_body = markdown.markdown(text, extensions=['extra', 'nl2br', 'sane_lists'])
    
    # Convert Mermaid code blocks into `<div class="mermaid">` blocks
    def replace_mermaid(match):
        code = match.group(1)
        # Unescape HTML entities that might have been escaped by markdown parser
        unescaped_code = html.unescape(code)
        # Strip leading/trailing whitespace
        unescaped_code = unescaped_code.strip()
        return f'<div class="mermaid">{unescaped_code}</div>'
    
    # Standard code block format output by markdown library:
    # <pre><code class="language-mermaid">...</code></pre>
    html_body = re.sub(
        r'<pre><code class="language-mermaid">([\s\S]*?)</code></pre>',
        replace_mermaid,
        html_body
    )
    
    # Sometimes it can also output as:
    # <pre><code class="mermaid">...</code></pre>
    html_body = re.sub(
        r'<pre><code class="mermaid">([\s\S]*?)</code></pre>',
        replace_mermaid,
        html_body
    )
    
    title = Path(md_path).stem
    full_html = HTML_TEMPLATE.format(title=title, content=html_body)
    
    print(f"Writing temporary HTML to {html_path}...")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(full_html)

def render_html_to_pdf(html_path, pdf_path):
    from playwright.sync_api import sync_playwright
    
    chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(chrome_path):
        print(f"Error: Chrome binary not found at {chrome_path}", file=sys.stderr)
        sys.exit(1)
        
    print(f"Launching Playwright with Chrome at {chrome_path}...")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=chrome_path,
            headless=True
        )
        page = browser.new_page()
        
        # Open the local HTML file
        abs_html_path = os.path.abspath(html_path)
        url = f"file://{abs_html_path}"
        print(f"Navigating to {url}...")
        page.goto(url)
        
        # Wait for Mermaid to finish rendering.
        # We can look for the SVG element inside .mermaid divs, or wait for network idle.
        # Also wait for a moment just in case.
        print("Waiting for page loads and Mermaid to render...")
        try:
            page.wait_for_selector(".mermaid svg", timeout=5000)
            print("Mermaid diagrams found and rendered.")
        except Exception as e:
            print("Warning: Mermaid SVG not found or timed out. Maybe no mermaid diagrams or slow rendering.")
            
        page.wait_for_timeout(1000)  # Extra buffer for rendering animations/fonts
        
        # Print to PDF
        print(f"Saving PDF to {pdf_path}...")
        page.pdf(
            path=pdf_path,
            format="A4",
            print_background=True,
            margin={
                "top": "20mm",
                "bottom": "20mm",
                "left": "20mm",
                "right": "20mm"
            }
        )
        browser.close()
    print("PDF generation complete!")

def main():
    docs_dir = Path("/Users/suyoo/Documents/works/agents-runtime/docs")
    files_to_convert = ["개발가이드.md", "운영가이드.md"]
    
    for filename in files_to_convert:
        md_file = docs_dir / filename
        if not md_file.exists():
            print(f"File not found: {md_file}", file=sys.stderr)
            continue
            
        html_file = docs_dir / f"{md_file.stem}.html"
        pdf_file = docs_dir / f"{md_file.stem}.pdf"
        
        print(f"\n=== Processing {filename} ===")
        convert_md_to_html(str(md_file), str(html_file))
        
        try:
            render_html_to_pdf(str(html_file), str(pdf_file))
        finally:
            # Clean up the temporary HTML file
            if html_file.exists():
                print(f"Cleaning up temporary {html_file.name}...")
                html_file.unlink()

if __name__ == "__main__":
    main()
