     # Публикуем
     success = False
     if local_img_path:
         success = send_photo_to_telegram(telegram_caption, local_img_path, bot_token, chat_id)
     if not success:
         success = send_text_to_telegram(telegram_caption, bot_token, chat_id)
