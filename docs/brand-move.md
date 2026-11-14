# Перенесення бренду Moo Toot на новий канал

Новий канал: https://www.youtube.com/@YogaForHealth-z9e. Його 11 відео про дитячу йогу
лишаються публічними, їх не чіпаємо. Усе нижче ви змінюєте самі в YouTube Studio →
**Customization** («Налаштування каналу»).

## 1. Назва — вкладка «Basic info» / «Основна інформація»

```
Moo Toot
```

YouTube дозволяє змінити назву двічі за 14 днів.

## 2. Аватар — вкладка «Branding» / «Брендинг» → Picture → Change

Файл: `C:\yt-kids\assets\channel\avatar.png` (800×800). Як він виглядає в маленькому
розмірі: `avatar_preview_98.png` і `avatar_preview_36.png` у тій самій папці.

## 3. Банер — «Branding» → Banner image → Change

Файл: `C:\yt-kids\assets\channel\banner.jpg` (2560×1440, менше 6 МБ). Безпечна зона, яку
видно на телефоні: `banner_preview_safe_area.jpg`.

## 4. Опис — «Basic info» → Description

```
Moo Toot is a learning channel for toddlers and preschoolers, ages 2 to 6.

Every video is real footage, not cartoons: a farm, an ocean, a garden, a busy street. Each
thing is shown, named slowly, and heard - the real moo, the real splash, the real engine - with
a pause so your child can say the word back. Then comes "Guess who?": a small piece of the
picture, a countdown, and the big reveal.

New videos every Tuesday, Thursday and Saturday.

Every video has a new set of animals, vehicles and foods - nothing is repeated.

Made for kids. Best watched together.
```

## 5. Ключові слова — Settings («Налаштування») → Channel → Basic info → Keywords

```
toddler learning, learning videos for toddlers, first words, animal sounds for kids, real animal sounds, farm animals for toddlers, vehicles for kids, preschool learning, kindergarten learning, guess the animal, educational videos for kids, speech practice for toddlers, kids yoga
```

«kids yoga» лишено свідомо: на каналі залишаються 11 відео про дитячу йогу.

## 6. «Made for kids» — Settings → Channel → Advanced settings

Audience: **Yes, set this channel as made for kids**. Кожне завантаження й так позначається
як made for kids (`selfDeclaredMadeForKids: true` у коді), але налаштування каналу має з цим
збігатися. Зверніть увагу: це налаштування поширюється й на 11 відео про йогу. Для дитячої
йоги це правильно, але ці відео теж втратять коментарі й персоналізовану рекламу.

## 7. Handle — чи переносити @MooToot

Раджу **не переносити**, а дати новому каналу схожий вільний handle, наприклад `@MooTootKids`
або `@MooTootLearning` (Studio → Customization → Basic info → Handle; YouTube одразу скаже,
чи він вільний).

Чому:
- старий handle має цінність лише тоді, коли за ним стоять глядачі, а на Moo Toot їх 0;
- перенесення не атомарне. Спершу @MooToot звільняють на старому каналі (змінюють на інший),
  і він якийсь час лишається закріпленим за старим каналом. Наскільки я знаю правила YouTube,
  це 14 днів, але перевірте в довідці YouTube «Change your handle», бо я не можу цього
  підтвердити напевно. Лише після цього handle стає вільним для будь-кого, і тоді його треба
  встигнути зайняти на новому каналі раніше за інших.

Якщо все ж переносити, безпечний порядок такий:
1. На новому каналі спершу поставте тимчасовий handle (`@MooTootKids`), щоб канал не
   лишався з `@YogaForHealth-z9e`.
2. На Moo Toot змініть handle на `@MooToot-archive`.
3. Коли YouTube звільнить `@MooToot` (за довідкою — див. вище), одразу займіть його на
   новому каналі.
4. Старі посилання `youtube.com/@MooToot` весь цей час вестимуть не туди, тож у описах
   нових відео handle не згадується (код його не пише).
