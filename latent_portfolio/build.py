#!/usr/bin/env python3
"""
Build script to prepare static site for deployment.
Copies source files from src/ to public/ and runs the processing pipeline.
"""

import shutil
import argparse
import re
import os
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional
import jinja2
import markdown
try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # Python < 3.11

# Import process module
from latent_portfolio.process import main as process_main
from latent_portfolio.load import load_markdown_files
from latent_portfolio import __version__


def load_config(config_path: Path) -> Dict[str, Any]:
    """
    Load configuration from TOML file.
    
    Args:
        config_path: Path to config.toml file
        
    Returns:
        Dictionary containing configuration
    """
    if not config_path.exists():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    
    with open(config_path, 'rb') as f:
        return tomllib.load(f)


def calculate_assets_version_hash(src_dir: Path, public_dir: Path, 
                                   config: Dict[str, Any], 
                                   embeddings_file: Optional[str] = None) -> str:
    """
    Calculate a version hash from all JS and CSS files.
    This hash will be used as a query parameter for cache-busting.
    
    Args:
        src_dir: Source directory (latent_portfolio/src)
        public_dir: Output directory (latent_portfolio/public) where files are copied
        config: Configuration dictionary
        embeddings_file: Optional embeddings filename
        
    Returns:
        Version hash string (first 8 characters)
    """
    # Collect all file contents that affect the build
    file_contents = []
    
    # Collect JS files
    js_src = src_dir / 'js'
    if js_src.exists():
        js_files = sorted(js_src.glob('*.js'))
        for js_file in js_files:
            if js_file.name == 'conf.js':
                # For conf.js, use the processed content
                js_conf = config.get('js-conf', {})
                style_config = config.get('style', {})
                font_cards = style_config.get('font-cards', 'Space Grotesk')
                content = process_conf_js(js_file, js_conf, font_cards, embeddings_file)
                file_contents.append(f"{js_file.name}:{content}")
            else:
                content = js_file.read_bytes()
                file_contents.append(f"{js_file.name}:{content}")
    
    # Collect CSS files
    css_src = src_dir / 'css'
    if css_src.exists():
        css_files = sorted(css_src.glob('*.css'))
        style_config = config.get('style', {})
        font_general = style_config.get('font-general', 'Noto Sans')
        font_cards = style_config.get('font-cards', 'Space Grotesk')
        bg_pattern = style_config.get('bg_pattern', 'diagonal.png')
        for css_file in css_files:
            # Use processed CSS content
            content = process_css_file(css_file, font_general, font_cards, bg_pattern)
            file_contents.append(f"{css_file.name}:{content}")
    
    # Combine all contents and calculate hash
    combined = '\n'.join(file_contents)
    full_hash = hashlib.sha256(combined.encode('utf-8')).hexdigest()
    
    # Return first 8 characters for shorter query string
    return full_hash[:8]


def normalize_base_url(base_url: str) -> str:
    """
    Normalize base_url to ensure consistent format.
    - Empty string stays empty
    - Paths without trailing slash get one added
    - Root path "/" stays as "/"
    
    Args:
        base_url: Base URL string from config
        
    Returns:
        Normalized base URL
    """
    if not base_url:
        return ""
    # Remove leading/trailing whitespace
    base_url = base_url.strip()
    # Ensure it starts with /
    if not base_url.startswith('/'):
        base_url = '/' + base_url
    # Ensure it ends with / (unless it's just "/")
    if base_url != '/' and not base_url.endswith('/'):
        base_url = base_url + '/'
    return base_url


def render_templates(src_dir: Path, public_dir: Path, config: Dict[str, Any], 
                    assets_version: Optional[str] = None):
    """
    Render Jinja2 templates from src/templates/ to public/.
    
    Args:
        src_dir: Source directory (latent_portfolio/src)
        public_dir: Output directory (latent_portfolio/public)
        config: Configuration dictionary
        assets_version: Optional version hash for cache-busting JS/CSS files
        
    Returns:
        Jinja2 environment for reuse
    """
    print("📄 Rendering HTML templates...")
    
    templates_dir = src_dir / 'templates'
    if not templates_dir.exists():
        print(f"  ⚠ Warning: {templates_dir} not found")
        return None
    
    user_templates_dir = src_dir / 'user_templates'
    
    # Normalize base_url
    if 'site' not in config:
        config['site'] = {}
    base_url = normalize_base_url(config['site'].get('base_url', ''))
    config['site']['base_url'] = base_url
    
    # Set up Jinja2 environment with ChoiceLoader to search both templates and user_templates
    loaders = [jinja2.FileSystemLoader(str(templates_dir))]
    if user_templates_dir.exists():
        loaders.append(jinja2.FileSystemLoader(str(user_templates_dir)))
    
    env = jinja2.Environment(
        loader=jinja2.ChoiceLoader(loaders),
        autoescape=jinja2.select_autoescape(['html', 'xml'])
    )
    
    # Add filter to prepend base_url and append version hash to JS/CSS files
    def url_filter(path: str) -> str:
        """Prepend base_url to a path and append version hash for JS/CSS files."""
        # Check if this is a JS or CSS file that should get cache-busting
        is_js_or_css = path.endswith('.js') or path.endswith('.css')
        
        # Append version hash as query parameter for JS/CSS files
        if is_js_or_css and assets_version:
            # Check if path already has a query string
            if '?' in path:
                path = f"{path}&v={assets_version}"
            else:
                path = f"{path}?v={assets_version}"
        
        if not base_url:
            return path
        # Remove leading slash from path if it exists (we'll add base_url which ends with /)
        path = path.lstrip('/')
        return base_url + path
    
    env.filters['url'] = url_filter
    
    # Add markdown filter
    def markdown_filter(text: str) -> str:
        """Convert markdown text to HTML."""
        return markdown.markdown(text)
    
    env.filters['markdown'] = markdown_filter
    
    # Get font config for critical CSS processing
    style_config = config.get('style', {})
    font_general = style_config.get('font-general', 'Noto Sans')
    font_cards = style_config.get('font-cards', 'Space Grotesk')
    bg_pattern = style_config.get('bg_pattern', 'diagonal.png')
    
    # Add global function to read critical CSS using existing process_css_file
    def get_critical_css() -> str:
        """Read and process critical.css file using existing CSS processing."""
        critical_css_path = src_dir / 'css' / 'critical.css'
        if not critical_css_path.exists():
            return ""
        # Reuse existing process_css_file function
        return process_css_file(critical_css_path, font_general, font_cards, bg_pattern)
    
    env.globals['critical_css'] = get_critical_css
    
    # Render index.html
    template = env.get_template('index.html')
    page_url = apply_base_url('index.html', base_url) if base_url else None
    output = template.render(config=config, page_url=page_url, version=__version__)
    
    output_file = public_dir / 'index.html'
    output_file.write_text(output, encoding='utf-8')
    print(f"  ✓ index.html rendered")

    # Render home.html
    template = env.get_template('home.html')
    page_url = apply_base_url('home.html', base_url) if base_url else None
    output = template.render(config=config, page_url=page_url, version=__version__)
    
    output_file = public_dir / 'home.html'
    output_file.write_text(output, encoding='utf-8')
    print(f"  ✓ home.html rendered")

    # Render 404.html
    template = env.get_template('404.html')
    page_url = apply_base_url('404.html', base_url) if base_url else None
    output = template.render(config=config, page_url=page_url, version=__version__)
    
    output_file = public_dir / '404.html'
    output_file.write_text(output, encoding='utf-8')
    print(f"  ✓ 404.html rendered")
    
    return env  # Return environment for reuse


def build_google_fonts_url(font_general: str, font_cards: str) -> str:
    """
    Build Google Fonts URL from font names.
    
    Args:
        font_general: General font name
        font_cards: Card font name
        
    Returns:
        Google Fonts URL string
    """
    # Convert font names to URL format (replace spaces with +)
    font_general_encoded = font_general.replace(' ', '+')
    font_cards_encoded = font_cards.replace(' ', '+')
    
    # Build URL with optimized weights/styles
    # font-general: italics and weights 100-900)
    # font-cards: Only weights 400 (regular) and 700 (bold) are used in card rendering
    url = f"https://fonts.googleapis.com/css2?family={font_general_encoded}:ital,wght@0,200;0,400;1,400&family={font_cards_encoded}:wght@400;700&display=swap"
    return url


def process_css_file(css_path: Path, font_general: str, font_cards: str, bg_pattern: str = None) -> str:
    """
    Process CSS file and update font variables and background pattern.
    
    Args:
        css_path: Path to CSS source file
        font_general: General font name
        font_cards: Card font name
        bg_pattern: Background pattern image filename (optional)
        
    Returns:
        Modified CSS content as string
    """
    if not css_path.exists():
        raise FileNotFoundError(f"CSS file not found: {css_path}")
    
    content = css_path.read_text(encoding='utf-8')
    
    # Replace font-family variable
    pattern = r'--font-family:\s*"[^"]+",\s*sans-serif;'
    replacement = f'--font-family: "{font_general}", sans-serif;'
    content = re.sub(pattern, replacement, content)
    
    # Replace font-mono variable (used for cards)
    pattern = r'--font-mono:\s*"[^"]+",\s*monospace;'
    replacement = f'--font-mono: "{font_cards}", monospace;'
    content = re.sub(pattern, replacement, content)
    
    # Replace bg-pattern variable if provided
    if bg_pattern:
        pattern = r"--bg-pattern:\s*url\(['\"][^'\"]+['\"]\);"
        replacement = f"--bg-pattern: url('{bg_pattern}');"
        content = re.sub(pattern, replacement, content)
    
    return content


def process_conf_js(conf_js_path: Path, js_conf: Dict[str, Any], font_cards: str = None, embeddings_file: str = None) -> str:
    """
    Process conf.js file and replace constants with values from js_conf.
    
    Args:
        conf_js_path: Path to conf.js source file
        js_conf: Dictionary of JavaScript configuration overrides
        
    Returns:
        Modified conf.js content as string
    """
    if not conf_js_path.exists():
        raise FileNotFoundError(f"conf.js not found: {conf_js_path}")
    
    content = conf_js_path.read_text(encoding='utf-8')
    
    # Apply font_cards to FONT_NAME if provided
    if font_cards:
        pattern = r'const\s+FONT_NAME\s*=\s*[^;]+;'
        replacement = f'const FONT_NAME = "{font_cards}";'
        if re.search(pattern, content):
            content = re.sub(pattern, replacement, content)
            print(f"  ↻ Override FONT_NAME = \"{font_cards}\"")
    
    # Apply embeddings_file to EMBEDDINGS_FILE if provided
    if embeddings_file:
        pattern = r'const\s+EMBEDDINGS_FILE\s*=\s*[^;]+;'
        replacement = f'const EMBEDDINGS_FILE = "{embeddings_file}";'
        if re.search(pattern, content):
            content = re.sub(pattern, replacement, content)
            print(f"  ↻ Override EMBEDDINGS_FILE = \"{embeddings_file}\"")
    
    if not js_conf:
        return content
    
    # Process each configuration override
    for key, value in js_conf.items():
        # Skip comments
        if key.startswith('#'):
            continue
        
        # Convert value to JavaScript representation
        if isinstance(value, bool):
            js_value = 'true' if value else 'false'
        elif isinstance(value, str):
            # Escape quotes and wrap in quotes
            escaped = value.replace('\\', '\\\\').replace('"', '\\"')
            js_value = f'"{escaped}"'
        elif isinstance(value, (int, float)):
            js_value = str(value)
        elif isinstance(value, dict):
            # Handle objects like CAMERA_INITIAL_POSITION
            if key == 'CAMERA_INITIAL_POSITION':
                js_value = f'{{ x: {value.get("x", 20)}, y: {value.get("y", 10)}, z: {value.get("z", 20)} }}'
            else:
                # Generic object handling - convert each value appropriately
                items = []
                for k, v in value.items():
                    if isinstance(v, str):
                        items.append(f'{k}: "{v}"')
                    elif isinstance(v, bool):
                        items.append(f'{k}: {"true" if v else "false"}')
                    else:
                        items.append(f'{k}: {v}')
                js_value = f'{{ {", ".join(items)} }}'
        elif isinstance(value, list):
            # Handle arrays
            items = ', '.join(f'"{item}"' if isinstance(item, str) else str(item) for item in value)
            js_value = f'[{items}]'
        else:
            # Fallback: convert to string
            js_value = f'"{str(value)}"'
        
        # Replace constant definition using regex
        # Match: const NAME = value;
        pattern = rf'const\s+{re.escape(key)}\s*=\s*[^;]+;'
        replacement = f'const {key} = {js_value};'
        
        if re.search(pattern, content):
            content = re.sub(pattern, replacement, content)
            print(f"  ↻ Override {key} = {js_value}")
        else:
            print(f"  ⚠ Warning: Constant {key} not found in conf.js")
    
    return content


def copy_source_files(src_dir: Path, public_dir: Path, config: Dict[str, Any], embeddings_file: str = None) -> Optional[str]:
    """
    Copy all source files from src/ to public/.
    
    Args:
        src_dir: Source directory (latent_portfolio/src)
        public_dir: Output directory (latent_portfolio/public)
        config: Configuration dictionary
        embeddings_file: Optional embeddings filename
        
    Returns:
        Version hash string for cache-busting, or None
    """
    print("🏗️  Building static site...")
    
    # Ensure public directory exists
    public_dir.mkdir(exist_ok=True)
    
    # 2. Copy JavaScript files
    print("📜 Copying JavaScript files...")
    js_src = src_dir / 'js'
    if js_src.exists():
        js_files = list(js_src.glob('*.js'))
        if js_files:
            # Get js-conf overrides if present
            js_conf = config.get('js-conf', {})
            
            # Get style config for font-cards
            style_config = config.get('style', {})
            font_cards = style_config.get('font-cards', 'Space Grotesk')
            
            for js_file in js_files:
                output_path = public_dir / js_file.name
                
                # Special handling for conf.js - apply overrides
                if js_file.name == 'conf.js':
                    if js_conf or font_cards or embeddings_file:
                        print(f"  🔧 Processing {js_file.name} with config overrides...")
                        processed_content = process_conf_js(js_file, js_conf, font_cards, embeddings_file)
                        output_path.write_text(processed_content, encoding='utf-8')
                        print(f"  ✓ {js_file.name}")
                    else:
                        shutil.copy(js_file, output_path)
                        print(f"  ✓ {js_file.name}")
                else:
                    shutil.copy(js_file, output_path)
                    print(f"  ✓ {js_file.name}")
        else:
            print("  ⚠ No JavaScript files found")
    else:
        print(f"  ⚠ Warning: {js_src} not found")
    
    # 3. Copy CSS files
    print("🎨 Copying CSS files...")
    css_src = src_dir / 'css'
    if css_src.exists():
        css_files = list(css_src.glob('*.css'))
        if css_files:
            # Get style config if present
            style_config = config.get('style', {})
            font_general = style_config.get('font-general', 'Noto Sans')
            font_cards = style_config.get('font-cards', 'Space Grotesk')
            bg_pattern = style_config.get('bg_pattern', 'diagonal.png')
            
            for css_file in css_files:
                output_path = public_dir / css_file.name
                # Process CSS to update font variables and background pattern
                processed_css = process_css_file(css_file, font_general, font_cards, bg_pattern)
                output_path.write_text(processed_css, encoding='utf-8')
                print(f"  ✓ {css_file.name}")
        else:
            print("  ⚠ No CSS files found")
    else:
        print(f"  ⚠ Warning: {css_src} not found")
    
    # 4. Copy static assets
    print("🖼️  Copying static assets...")
    assets_src = src_dir / 'assets'
    if assets_src.exists():
        assets = [a for a in assets_src.iterdir() if a.is_file()]
        if assets:
            for asset in assets:
                shutil.copy(asset, public_dir / asset.name)
                print(f"  ✓ {asset.name}")
        else:
            print("  ⚠ No asset files found")
    else:
        print(f"  ⚠ Warning: {assets_src} not found")
    
    # Calculate version hash after copying all files
    print("🔢 Calculating assets version hash...")
    assets_version = calculate_assets_version_hash(src_dir, public_dir, config, embeddings_file)
    print(f"  ✓ Assets version: {assets_version}")
    
    print("✅ Source files copied\n")
    return assets_version


def apply_base_url(path: str, base_url: str) -> str:
    """
    Apply base_url to a path if base_url is set and path is not already a full URL.
    
    Args:
        path: Path to apply base_url to
        base_url: Base URL (normalized, ends with / or empty)
        
    Returns:
        Path with base_url prepended if applicable
    """
    if not base_url or not path:
        return path
    
    # Don't modify full URLs (http/https)
    if path.startswith(('http://', 'https://')):
        return path
    
    # Remove leading slash from path if it exists (base_url already ends with /)
    path = path.lstrip('/')
    return base_url + path


def render_article_pages(src_dir: Path, public_dir: Path, config: Dict[str, Any], base_url: str, articles_data: Dict[str, Dict], assets_version: Optional[str] = None):
    """
    Render article HTML pages using the single.html template.
    
    Args:
        src_dir: Source directory (latent_portfolio/src)
        public_dir: Output directory (latent_portfolio/public)
        config: Configuration dictionary
        base_url: Base URL for paths
        articles_data: Pre-loaded article data dictionary
        assets_version: Optional version hash for cache-busting JS/CSS files
    """
    print("📝 Rendering article pages...")
    
    templates_dir = src_dir / 'templates'
    if not templates_dir.exists():
        print(f"  ⚠ Warning: {templates_dir} not found")
        return
    
    user_templates_dir = src_dir / 'user_templates'
    
    # Normalize base_url
    if 'site' not in config:
        config['site'] = {}
    base_url = normalize_base_url(base_url)
    config['site']['base_url'] = base_url
    
    # Set up Jinja2 environment with ChoiceLoader to search both templates and user_templates
    loaders = [jinja2.FileSystemLoader(str(templates_dir))]
    if user_templates_dir.exists():
        loaders.append(jinja2.FileSystemLoader(str(user_templates_dir)))
    
    env = jinja2.Environment(
        loader=jinja2.ChoiceLoader(loaders),
        autoescape=jinja2.select_autoescape(['html', 'xml'])
    )
    
    # Add filter to prepend base_url and append version hash to JS/CSS files
    def url_filter(path: str) -> str:
        """Prepend base_url to a path and append version hash for JS/CSS files."""
        # Check if this is a JS or CSS file that should get cache-busting
        is_js_or_css = path.endswith('.js') or path.endswith('.css')
        
        # Append version hash as query parameter for JS/CSS files
        if is_js_or_css and assets_version:
            # Check if path already has a query string
            if '?' in path:
                path = f"{path}&v={assets_version}"
            else:
                path = f"{path}?v={assets_version}"
        
        if not base_url:
            return path
        path = path.lstrip('/')
        return base_url + path
    
    env.filters['url'] = url_filter
    
    # Add markdown filter
    def markdown_filter(text: str) -> str:
        """Convert markdown text to HTML."""
        return markdown.markdown(text)
    
    env.filters['markdown'] = markdown_filter
    
    # Get font config for critical CSS processing
    style_config = config.get('style', {})
    font_general = style_config.get('font-general', 'Noto Sans')
    font_cards = style_config.get('font-cards', 'Space Grotesk')
    bg_pattern = style_config.get('bg_pattern', 'diagonal.png')
    
    # Add global function to read critical CSS using existing process_css_file
    def get_critical_css() -> str:
        """Read and process critical.css file using existing CSS processing."""
        critical_css_path = src_dir / 'css' / 'critical.css'
        if not critical_css_path.exists():
            return ""
        # Reuse existing process_css_file function
        return process_css_file(critical_css_path, font_general, font_cards, bg_pattern)
    
    env.globals['critical_css'] = get_critical_css
    
    # Ensure articles_data is provided
    if articles_data is None:
        raise ValueError("articles_data must be provided")
    
    # Get single.html template
    template = env.get_template('single.html')
    
    # Render each article
    for key, article in articles_data.items():
        # Get HTML content from article (already converted from markdown)
        html_content = article.get('html_content', '')
        
        # Update image paths to point to images folder
        def replace_img_src(match):
            src_value = match.group(1)
            
            # Don't modify full URLs (http/https)
            if src_value.startswith(('http://', 'https://')):
                return f'src="{src_value}"'
            
            # If already pointing to images folder, just apply base_url
            if src_value.startswith('images/'):
                new_path = src_value
            else:
                # Extract filename from path
                filename = os.path.basename(src_value)
                
                # Check if image exists in images folder
                images_folder = public_dir / 'images'
                image_path = images_folder / filename
                
                # If image exists in images folder, update path
                if image_path.exists():
                    new_path = f'images/{filename}'
                else:
                    # Keep original path if image not found
                    new_path = src_value
            
            # Apply base_url if provided
            if base_url:
                new_path = apply_base_url(new_path, base_url)
            
            return f'src="{new_path}"'
        
        html_content = re.sub(r'src="([^"]+)"', replace_img_src, html_content)
        
        # Render template with article content
        article_image = article.get('image', None)
        # Only pass image if it's a valid string (not False or None)
        if not article_image or article_image is False:
            article_image = None

        
        # Construct page URL
        page_url = None
        if base_url:
            page_url = apply_base_url(f"{key}.html", base_url)
        
        output = template.render(
            config=config,
            article_content=html_content,
            article_title=article.get('title', ''),
            article_description=article.get('description', ''),
            article_image=article_image,
            article_id=article.get('id'),
            page_url=page_url,
            version=__version__
        )
        
        # Save rendered HTML file
        html_filename = f"{key}.html"
        output_file = public_dir / html_filename
        output_file.write_text(output, encoding='utf-8')
        print(f"  ✓ {html_filename}")
    
    print(f"  ✅ Rendered {len(articles_data)} article pages")


def build(
    input_folder: str = None,
    output_dir: str = None,
    methods: List[str] = None,
    dimensions: List[int] = None,
    skip_confirmation: bool = False,
    copy_only: bool = False,
    config_path: str = None,
    base_url: str = None,
    thumbnail_res: str = '400x210'
):
    """
    Main build function that copies source files and runs processing pipeline.
    
    Args:
        input_folder: Path to folder containing markdown files (default: articles/ relative to build.py)
        output_dir: Output directory for build (default: build/public/ relative to project root)
        methods: Dimensionality reduction methods to use (default: ['pca'])
        dimensions: Output dimensions (default: [3])
        skip_confirmation: Skip confirmation prompts
        copy_only: Only copy source files, skip processing
        config_path: Path to config.toml file (default: config.toml relative to build.py)
        base_url: Base URL override (default: None, uses config file value)
        thumbnail_res: Thumbnail resolution in format WIDTHxHEIGHT (default: '400x210')
    """
    print(f"Latent Portfolio version: {__version__}")
    # Define paths relative to this file
    latent_portfolio_dir = Path(__file__).parent
    project_root = latent_portfolio_dir.parent
    src_dir = latent_portfolio_dir / 'src'
    
    # Set defaults relative to this file
    if output_dir is None:
        output_dir = str(project_root / 'public')
    if input_folder is None:
        input_folder = str(project_root / 'sample_articles')
    if methods is None:
        methods = ['pca']
    if dimensions is None:
        dimensions = [3]
    if config_path is None:
        config_path = str(project_root / 'config.toml')
    
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # Load configuration
    config_path = Path(config_path)
    try:
        config = load_config(config_path)
    except FileNotFoundError as e:
        print(f"Configuration file not found: {config_path}")
        if config_path.with_suffix('.toml.template').exists():
            if not skip_confirmation:
                print("<<< ⚠️  A custom configuration file is missing. (config.toml) ⚠️  >>>")
                print("You can use the template configuration file for a quick start (config.toml.template), but note that any changes you make to it may be overridden when you pull updates from the upstream repository.")
                print("Would you like to use the template configuration file for now? (y/n)")
                answer = input()
                if answer != 'y':
                    print("❌ Confirmation not given. Exiting...")
                    exit(1)

            config = load_config(config_path.with_suffix('.toml.template'))
            print(f"Using template configuration file: {config_path.with_suffix('.toml.template')}")
        else:
            print(f"❌ No template configuration file found at {config_path}. Exiting...")
            exit(1)
    
    # Normalize base_url (use command-line override if provided, otherwise use config)
    if 'site' not in config:
        config['site'] = {}
    if base_url is not None:
        # Use command-line override
        base_url = normalize_base_url(base_url)
    else:
        # Use config file value
        base_url = normalize_base_url(config['site'].get('base_url', ''))
    config['site']['base_url'] = base_url
    
    # Process style configuration
    if 'style' not in config:
        config['style'] = {}
    font_general = config['style'].get('font-general', 'Noto Sans')
    font_cards = config['style'].get('font-cards', 'Space Grotesk')
    config['style']['google_fonts_url'] = build_google_fonts_url(font_general, font_cards)
    
    # Step 1: Copy source files (without embeddings_file initially)
    assets_version = copy_source_files(src_dir, output_path, config, embeddings_file=None)
    
    # Step 2: Run processing pipeline (if not copy_only)
    embeddings_filename = None
    if not copy_only:
        print("🔄 Running processing pipeline...")
        
        try:
            # Load article data once
            articles_data, errors, warnings = load_markdown_files(
                input_folder,
                str(output_path),
                skip_confirmation,
                base_url,
                thumbnail_res
            )
            if len(articles_data) < 4:
                print("<<< ❌ Not enough articles. ❌ >>>")
                print("You need at least 4 articles to generate significant dimensionality reductions.")
                print("Please add more articles to the input folder and try again.")
                print(" ❌ Build aborted.")
                exit(1)
            
            ids = [i['id'] for i in articles_data.values()]
            if len(ids) != len(set(ids)):
                print("<<< ❌ Duplicate IDs found. ❌ >>>")
                print(f"Duplicate IDs: {set([ f'{idx:03d}' for idx in ids if ids.count(idx) > 1])}")
                print("Please ensure each article has a unique ID.")
                print(" ❌ Build aborted.")
                exit(1)

            # Pass pre-loaded data to process_main
            # Extract weights from config (default to empty dict if not present)
            weights = config.get('weights', {})
            # Extract rotation from config (default to [0, 0, 0] if not present)
            rotation_config = config.get('rotation', {})
            rotation = [
                rotation_config.get('x', 0),
                rotation_config.get('y', 0),
                rotation_config.get('z', 0)
            ]
            embeddings_filename = process_main(
                data=articles_data,
                output_folder=str(output_path),
                methods=methods,
                dimensions=dimensions,
                weights=weights,
                rotation=rotation
            )
            
            # Update conf.js with the embeddings filename
            if embeddings_filename:
                js_src = src_dir / 'js'
                conf_js_path = js_src / 'conf.js'
                if conf_js_path.exists():
                    print("📝 Updating conf.js with embeddings filename...")
                    js_conf = config.get('js-conf', {})
                    style_config = config.get('style', {})
                    font_cards = style_config.get('font-cards', 'Space Grotesk')
                    processed_content = process_conf_js(conf_js_path, js_conf, font_cards, embeddings_filename)
                    (output_path / 'conf.js').write_text(processed_content, encoding='utf-8')
                    print(f"  ✓ Updated conf.js with EMBEDDINGS_FILE = \"{embeddings_filename}\"")
                    
                    # Recalculate assets version since conf.js changed
                    assets_version = calculate_assets_version_hash(src_dir, output_path, config, embeddings_filename)
                    print(f"  ↻ Recalculated assets version: {assets_version}")
            
            # Step 3: Render HTML templates with assets version
            render_templates(src_dir, output_path, config, assets_version)
            
            # Step 4: Render article pages using single.html template (pass pre-loaded data)
            render_article_pages(src_dir, output_path, config, base_url, articles_data, assets_version)
            
            print("\n✅ Build complete!")
            print(f"   Latent Portfolio version: {__version__}")
            print(f"📦 Output directory: {output_path}")
            if embeddings_filename:
                print(f"📊 Embeddings file: {embeddings_filename}")

            if warnings:
                print("\n============ Warnings processing articles =============")
                for warning in warnings:
                    print(f"\n  ⚠️ {warning}")
            if errors:
                print("\n============ Errors processing articles =============")
                for error in errors:
                    print(f"\n  ❌ {error}")
            
        except Exception as e:
            print(f"\n❌ Error during processing: {e}")
            raise
    else:
        # Render templates even in copy-only mode (for assets version)
        render_templates(src_dir, output_path, config, assets_version)
        print("✅ Build complete (source files only)")
        print(f"  Latent Portfolio version: {__version__}")
        print(f"📦 Output directory: {output_path}")
        print("\n💡 To generate embeddings, run:")
        print(f"   python -m latent_portfolio.process -i {input_folder} -o {output_path} --methods {' '.join(methods)} --dimensions {' '.join(map(str, dimensions))} -s")


def _run():
    """Main entrypoint for command-line interface"""
    parser = argparse.ArgumentParser(
        description='Build static site: copy source files and generate embeddings',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full build with default settings
  python -m latent_portfolio.build
  
  # Build with custom methods and dimensions
  python -m latent_portfolio.build --methods pca umap --dimensions 2 3
  
  # Build with custom input/output directories
  python -m latent_portfolio.build -i articles/ -o build/public/
  
  # Copy source files only (skip processing)
  python -m latent_portfolio.build --copy-only
        """
    )
    
    # Calculate default paths relative to this file
    latent_portfolio_dir = Path(__file__).parent
    project_root = latent_portfolio_dir.parent
    default_input = str(project_root / 'sample_articles')
    default_output = str(project_root / 'public')
    
    parser.add_argument(
        '--input', '-i',
        type=str,
        default=None,
        help=f'Input folder containing markdown files (default: {default_input})'
    )
    
    parser.add_argument(
        '--output', '-o',
        type=str,
        default=None,
        help=f'Output directory for build (default: {default_output})'
    )
    
    parser.add_argument(
        '--methods',
        type=str,
        nargs='+',
        choices=['pca', 'tsne', 'umap'],
        default=['pca'],
        help='Dimensionality reduction methods to use (default: pca)'
    )
    
    parser.add_argument(
        '--dimensions', '-d',
        type=int,
        nargs='+',
        choices=[2, 3],
        default=[3],
        help='Output dimensions (2D and/or 3D) (default: 3)'
    )
    
    parser.add_argument(
        '--skip-confirmation', '-s',
        action='store_true',
        help='Skip confirmation prompts'
    )
    
    parser.add_argument(
        '--copy-only',
        action='store_true',
        help='Only copy source files, skip processing pipeline'
    )
    
    parser.add_argument(
        '--config', '-c',
        type=str,
        default=None,
        help='Path to config.toml file (default: ../config.toml relative to build.py)'
    )
    
    parser.add_argument(
        '--base-url',
        type=str,
        default=None,
        help='Base URL for deployment (overrides config file value, e.g., "/subfolder")'
    )
    
    parser.add_argument(
        '--thumbnail-res',
        type=str,
        default='400x210',
        help='Thumbnail resolution in format WIDTHxHEIGHT (default: 400x210)'
    )
    
    args = parser.parse_args()
    
    build(
        input_folder=args.input,
        output_dir=args.output,
        methods=args.methods,
        dimensions=args.dimensions,
        skip_confirmation=args.skip_confirmation,
        copy_only=args.copy_only,
        config_path=args.config,
        base_url=args.base_url,
        thumbnail_res=args.thumbnail_res
    )


if __name__ == '__main__':
    _run()
