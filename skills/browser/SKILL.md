---
name: browser
description: "Управление браузером: открытие страниц, взаимодействие, история, закладки"
tools:
  - browser_open
  - browser_action
  - browser_history
  - browser_bookmarks
  - browser_close
trigger_keywords:
  - браузер
  - chrome
  - хром
  - открой сайт
  - открой ссылку
  - открой youtube
  - открой ютуб
  - открой gmail
  - открой почту
  - история браузера
  - закладки
  - bookmarks
  - закрой браузер
  - закрой хром
  - открой в браузере
  - что я смотрел
  - что я открывал
  - история посещений
  - нажми
  - кликни
  - заполни
  - залогинься
  - авторизуйся
  - скриншот страницы
  - инкогнито
---

# Управление браузером

## browser_open
Открыть URL в Chrome. Если Chrome запущен — откроет новую вкладку.
Примеры: url=youtube.com, url=https://mail.google.com
Если вместо URL написан текст (без точек), откроет как Google-поиск.
Параметры: incognito (true/false), new_window (true/false).

## browser_action
Взаимодействие со страницей через Playwright (отдельный браузер):
navigate, click, fill, type, select, press, scroll, screenshot, eval_js, wait

## browser_history
Показать историю посещений Chrome.

## browser_bookmarks
Показать закладки Chrome.

## browser_close
Закрыть Playwright-браузер (не Chrome).

## Примеры
"открой youtube" → browser_open url=youtube.com
"открой gmail" → browser_open url=mail.google.com
"открой инкогнито youtube" → browser_open url=youtube.com incognito=true
"нажми Login" → browser_action action=click selector="button:has-text('Login')"
"что я смотрел?" → browser_history
"покажи закладки" → browser_bookmarks
"закрой браузер" → browser_close
