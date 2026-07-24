import json
import os
import re
import datetime
import time
from xml.sax.saxutils import escape

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def format_dzen_html(post_text, image_url=None, extra_images=None, title=""):
    """
    Форматирует текст статьи под стандарты Яндекс Дзен:
    - Заголовки <h2> и <h3>
    - Цитаты <blockquote>
    - Изображения <figure><img src="..."/><figcaption>...</figcaption></figure>
    - Параграфы <p>
    """
    if not post_text:
        return ""

    lines = post_text.split('\n')
    html_parts = []
    
    # Главная обложка статьи
    if image_url:
        full_img_url = image_url if image_url.startswith('http') else f"https://maxtyutin.github.io/cryptochannel/{image_url.lstrip('/')}"
        html_parts.append(f'<figure><img src="{escape(full_img_url)}"/><figcaption>{escape(title)}</figcaption></figure>')
    
    extra_idx = 0
    extra_imgs = extra_images or []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
            
        # Заменяем плейсхолдеры [IMAGE: N] на <figure>
        if '[IMAGE:' in stripped:
            if extra_idx < len(extra_imgs):
                e_url = extra_imgs[extra_idx]
                full_e_url = e_url if e_url.startswith('http') else f"https://maxtyutin.github.io/cryptochannel/{e_url.lstrip('/')}"
                html_parts.append(f'<figure><img src="{escape(full_e_url)}"/><figcaption>Иллюстрация к материалу</figcaption></figure>')
                extra_idx += 1
            continue

        # Форматирование заголовков и цитат
        if stripped.startswith('##') or stripped.startswith('###'):
            header_text = re.sub(r'^#+\s*', '', stripped)
            html_parts.append(f'<h2>{escape(header_text)}</h2>')
        elif stripped.startswith('<b>') and stripped.endswith('</b>') and len(stripped) < 100:
            clean_hdr = re.sub(r'</?b>', '', stripped)
            html_parts.append(f'<h2>{escape(clean_hdr)}</h2>')
        elif '<blockquote>' in stripped or stripped.startswith('💬') or 'Заявление:' in stripped or 'Вывод:' in stripped:
            clean_quote = re.sub(r'</?blockquote>', '', stripped)
            html_parts.append(f'<blockquote>{escape(clean_quote)}</blockquote>')
        else:
            html_parts.append(f'<p>{stripped}</p>')

    return "\n".join(html_parts)

def generate_dzen_rss():
    """
    Генерирует валидный dzen.xml RSS-канал Яндекс Дзен со всеми статьями из articles.json
    """
    json_path = os.path.join(BASE_DIR, "articles.json")
    rss_path = os.path.join(BASE_DIR, "dzen.xml")
    
    if not os.path.exists(json_path):
        print("[dzen] articles.json не найден.")
        return

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            articles = json.load(f)
    except Exception as e:
        print(f"[dzen] Ошибка чтения articles.json: {e}")
        return

    rss_items = []
    
    for art in articles[:50]:  # Берем последние 50 статей для Дзена
        title = art.get('title', '')
        link = f"https://maxtyutin.github.io/cryptochannel/#article-{art.get('timestamp')}"
        ts = art.get('timestamp', int(time.time()))
        
        # Конвертируем timestamp в RFC 822 дата-время для RSS
        dt = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc)
        pub_date = dt.strftime("%a, %d %b %Y %H:%M:%S +0000")
        
        img_url = art.get('image_url', '')
        full_img_url = ""
        if img_url:
            full_img_url = img_url if img_url.startswith('http') else f"https://maxtyutin.github.io/cryptochannel/{img_url.lstrip('/')}"

        category = art.get('category', 'Crypto')
        post_text = art.get('post_text', '')
        extra_imgs = art.get('extra_images', [])
        
        dzen_content = format_dzen_html(post_text, image_url=full_img_url, extra_images=extra_imgs, title=title)
        
        enclosure_tag = f'<enclosure url="{escape(full_img_url)}" type="image/jpeg"/>' if full_img_url else ''

        item_xml = f"""    <item>
      <title>{escape(title)}</title>
      <link>{escape(link)}</link>
      <guid isPermaLink="false">{ts}</guid>
      <pubDate>{pub_date}</pubDate>
      <category>{escape(category)}</category>
      {enclosure_tag}
      <content:encoded><![CDATA[{dzen_content}]]></content:encoded>
    </item>"""
        rss_items.append(item_xml)

    items_str = "\n".join(rss_items)
    
    rss_xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" 
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:atom="http://www.w3.org/2005/Atom"
     xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <title>Crypto Analytics — Новости и аналитика криптовалют</title>
    <link>https://maxtyutin.github.io/cryptochannel/</link>
    <description>Главные новости криптовалют, аналитика рынка, биткоин, альткоины и финансовые рынки</description>
    <language>ru</language>
    <atom:link href="https://maxtyutin.github.io/cryptochannel/dzen.xml" rel="self" type="application/rss+xml" />
{items_str}
  </channel>
</rss>
"""

    with open(rss_path, 'w', encoding='utf-8') as f:
        f.write(rss_xml)
        
    print(f"[dzen] Успешно сгенерирована RSS-лента Яндекс Дзен ({len(articles[:50])} статей) -> {rss_path}")

if __name__ == "__main__":
    generate_dzen_rss()
