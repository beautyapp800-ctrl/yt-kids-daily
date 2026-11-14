# Токен YouTube для нового каналу (Yoga For Health → Moo Toot)

Канал: https://www.youtube.com/@YogaForHealth-z9e, ID `UCX71CVp9h0wn762YHzdo0QQ` (записано в
`config.json` як `youtube_channel_id`).

Новий токен має два дозволи: завантаження відео (`youtube.upload`) і перегляд облікового запису
(`youtube.readonly`). Другий потрібен лише для одного: щоб перед кожним завантаженням спитати
у YouTube, для якого каналу цей токен, і нічого не відправляти, якщо це не канал з
`config.json`. Старий токен Moo Toot такого дозволу не має, тому з ним завантаження тепер
відмовляються самі.

Ключі й токени вводите ви. У git вони не потрапляють: `secrets/` і `credentials.json` у
`.gitignore`.

## Перед входом

1. Файл `C:\yt-kids\credentials.json` має бути на місці (той самий OAuth-клієнт, що для
   Moo Toot, підходить: квота YouTube API рахується на проєкт Google Cloud, не на канал).
2. Google Cloud Console → APIs & Services → OAuth consent screen:
   - якщо статус **Testing**, а Yoga For Health належить іншому Google-акаунту, ніж
     Moo Toot, додайте цей акаунт у **Test users**;
   - у статусі Testing токен перестає працювати через 7 днів. Якщо можна, переведіть
     екран у **In production** (кнопка Publish app); для власного застосунку перевірка
     Google для цього не потрібна.

## Вхід

1. Відкрийте термінал і виконайте:

   ```
   cd C:\yt-kids
   python scripts\youtube_auth.py
   ```

2. Відкриється браузер. Виберіть **Google-акаунт**, якому належить Yoga For Health.
3. Якщо в акаунті кілька каналів, Google покаже сторінку **«Choose an account or brand
   account» / «Виберіть обліковий запис або обліковий запис бренду»**. Натисніть
   **Yoga For Health** — НЕ Moo Toot. Від цього кроку залежить усе.
4. «Google hasn't verified this app» / «Google не перевірив цей додаток» — це нормально для
   власного проєкту: **Advanced** («Додатково») → **Go to … (unsafe)** («Перейти до …»).
5. На сторінці дозволів залиште обидві галочки (керування/завантаження відео YouTube і
   перегляд облікового запису YouTube) → **Continue** / **Allow**.
6. Поверніться в термінал:
   - `The token is for 'Yoga For Health' @YogaForHealth-z9e (UCX71CVp9h0wn762YHzdo0QQ)` —
     усе правильно, токен збережено в `secrets\token.json`;
   - `NOT SAVED. the token is for channel 'Moo Toot' …` — вибрано не той канал, нічого не
     збережено; запустіть скрипт ще раз і на кроці 3 виберіть Yoga For Health.

## Секрет для GitHub

1. Відкрийте `C:\yt-kids\secrets\token.json` у Блокноті, виділіть усе (Ctrl+A), скопіюйте.
2. https://github.com/beautyapp800-ctrl/yt-kids-daily → **Settings** → **Secrets and
   variables** → **Actions** → `YOUTUBE_TOKEN_JSON` → **Update** → вставте → **Update secret**.
3. Напишіть мені, що секрет оновлено. Я ввімкну щоденний workflow (`daily`) і перевірю за
   першим прогоном: його preflight друкує, для якого каналу токен
   (`youtube token: channel 'Yoga For Health' … - the configured one`). Якщо там буде
   інший канал, прогін зупиниться до будь-якого завантаження.
