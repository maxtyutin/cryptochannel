import os
import sys
import base64

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def get_base64_avatar():
    avatar_path = os.path.join(BASE_DIR, "images/vitalik_avatar.jpg")
    if os.path.exists(avatar_path):
        with open(avatar_path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
            return f"data:image/jpeg;base64,{encoded}"
    return "https://unavatar.io/twitter/VitalikButerin"

def generate_tweet_card_html(
    author_name="vitalik.eth",
    author_handle="@VitalikButerin",
    avatar_url=None,
    date_str="15:01 · 21 июл. 2026 г.",
    tweet_text_en="",
    attached_img_url=None,
    views_str="301,9 тыс.",
    comments_cnt="340",
    retweets_cnt="149",
    likes_cnt="2 тыс.",
    bookmarks_cnt="234",
    output_html_path="tweet_card.html"
):
    """
    Генерирует HTML-шаблон твита с гарантированным отображением 100% реальной аватарки (Base64)
    и ПОЛНОГО текста твита в оригинале на английском языке.
    """
    if not avatar_url or avatar_url.startswith("http"):
        avatar_url = get_base64_avatar()
        
    img_html = ""
    if attached_img_url:
        img_html = f'<div class="media-container"><img src="{attached_img_url}" class="media-img"/></div>'

    formatted_text = tweet_text_en.replace("\n", "<br><br>")
        
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }}
  body {{ background: #ffffff; padding: 24px; display: inline-block; }}
  .tweet-card {{
    width: 600px;
    background: #ffffff;
    border: 1px solid #cfd9de;
    border-radius: 16px;
    padding: 16px 20px;
    box-shadow: 0 4px 12px rgba(0,0,0,0.04);
  }}
  .header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }}
  .author-info {{ display: flex; align-items: center; gap: 12px; }}
  .avatar {{ width: 48px; height: 48px; border-radius: 50%; object-fit: cover; border: 1px solid #e2e8f0; }}
  .name-box {{ display: flex; flex-direction: column; }}
  .name-row {{ display: flex; align-items: center; gap: 4px; }}
  .author-name {{ font-weight: 700; font-size: 16px; color: #0f1419; }}
  .verified-badge {{ width: 18px; height: 18px; fill: #1d9bf0; }}
  .author-handle {{ font-size: 15px; color: #536471; }}
  .more-btn {{ color: #536471; font-size: 18px; font-weight: bold; cursor: pointer; }}
  .tweet-text {{ font-size: 17px; line-height: 1.45; color: #0f1419; margin-bottom: 14px; word-wrap: break-word; }}
  .media-container {{ margin-bottom: 14px; border-radius: 12px; overflow: hidden; border: 1px solid #cfd9de; }}
  .media-img {{ width: 100%; max-height: 380px; object-fit: cover; display: block; }}
  .meta-row {{ font-size: 15px; color: #536471; border-bottom: 1px solid #eff3f4; padding-bottom: 12px; margin-bottom: 12px; display: flex; gap: 6px; align-items: center; }}
  .meta-views {{ font-weight: 700; color: #0f1419; }}
  .metrics-row {{ display: flex; justify-content: space-between; align-items: center; color: #536471; font-size: 14px; padding: 0 10px; }}
  .metric-item {{ display: flex; align-items: center; gap: 8px; }}
  .metric-icon {{ width: 18px; height: 18px; fill: #536471; }}
</style>
</head>
<body>

<div class="tweet-card">
  <div class="header">
    <div class="author-info">
      <img src="{avatar_url}" class="avatar" alt="Vitalik Avatar"/>
      <div class="name-box">
        <div class="name-row">
          <span class="author-name">{author_name}</span>
          <svg class="verified-badge" viewBox="0 0 24 24"><path d="M22.25 12c0-1.43-.88-2.67-2.19-3.19.46-1.39.02-2.9-1.08-3.99s-2.6-1.54-3.99-1.08C14.67 2.43 13.43 1.55 12 1.55s-2.67.88-3.19 2.19c-1.39-.46-2.9-.02-3.99 1.08s-1.54 2.6-1.08 3.99C2.43 9.33 1.55 10.57 1.55 12s.88 2.67 2.19 3.19c-.46 1.39-.02 2.9 1.08 3.99s2.6 1.54 3.99 1.08c.52 1.31 1.76 2.19 3.19 2.19s2.67-.88 3.19-2.19c1.39.46 2.9.02 3.99-1.08s1.54-2.6 1.08-3.99c1.31-.52 2.19-1.76 2.19-3.19zM9.6 17.2l-4.2-4.2 1.4-1.4 2.8 2.8 7.2-7.2 1.4 1.4-8.6 8.6z"/></svg>
        </div>
        <span class="author-handle">{author_handle}</span>
      </div>
    </div>
    <div class="more-btn">•••</div>
  </div>

  <div class="tweet-text">{formatted_text}</div>
  {img_html}

  <div class="meta-row">
    <span>{date_str}</span>
    <span>·</span>
    <span class="meta-views">{views_str}</span>
    <span>Просмотры</span>
  </div>

  <div class="metrics-row">
    <div class="metric-item">
      <svg class="metric-icon" viewBox="0 0 24 24"><path d="M1.751 10c0-4.42 3.584-8 8.005-8h4.488c4.42 0 8.005 3.58 8.005 8 0 3.58-2.357 6.61-5.617 7.61L12 22l-4.632-4.39C4.108 16.61 1.751 13.58 1.751 10z" fill="none" stroke="currentColor" stroke-width="2"/></svg>
      <span>{comments_cnt}</span>
    </div>
    <div class="metric-item">
      <svg class="metric-icon" viewBox="0 0 24 24"><path d="M4.5 3.88l4.432 4.14-1.364 1.46L5.5 7.55V16c0 1.1.9 2 2 2H14v2H7.5C5.57 20 4 18.43 4 16.5V7.55L1.932 9.48.568 8.02 4.5 3.88zM19.5 20.12l-4.432-4.14 1.364-1.46 2.068 1.93V8c0-1.1-.9-2-2-2H10V4h6.5C18.43 4 20 5.57 20 7.5v8.95l2.068-1.93 1.364 1.46-3.932 4.14z"/></svg>
      <span>{retweets_cnt}</span>
    </div>
    <div class="metric-item">
      <svg class="metric-icon" viewBox="0 0 24 24"><path d="M12 21.638h-.014C9.403 21.59 1.95 14.851 1.95 8.478 1.95 5.172 4.627 2.5 7.925 2.5c1.921 0 3.699.92 4.825 2.457 1.127-1.537 2.904-2.457 4.825-2.457 3.298 0 5.975 2.672 5.975 5.978 0 6.373-7.453 13.112-10.036 13.16H12z" fill="none" stroke="currentColor" stroke-width="2"/></svg>
      <span>{likes_cnt}</span>
    </div>
    <div class="metric-item">
      <svg class="metric-icon" viewBox="0 0 24 24"><path d="M4 4.5C4 3.12 5.12 2 6.5 2h11C18.88 2 20 3.12 20 4.5v17l-8-5.333L4 21.5v-17z" fill="none" stroke="currentColor" stroke-width="2"/></svg>
      <span>{bookmarks_cnt}</span>
    </div>
    <div class="metric-item">
      <svg class="metric-icon" viewBox="0 0 24 24"><path d="M12 2.59l5.7 5.7-1.41 1.42L13 6.41V16h-2V6.41L7.71 9.71 6.3 8.29 12 2.59zM21 15v5c0 1.1-.9 2-2 2H5c-1.1 0-2-.9-2-2v-5h2v5h14v-5h2z"/></svg>
    </div>
  </div>
</div>

</body>
</html>
"""
    with open(output_html_path, 'w', encoding='utf-8') as f:
        f.write(html_content)
    return output_html_path
