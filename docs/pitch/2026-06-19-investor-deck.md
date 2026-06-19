---
marp: true
size: 16:9
paginate: true
backgroundColor: "#0B0B0F"
color: "#E8E8EC"
style: |
  section {
    background: radial-gradient(120% 80% at 82% -12%, #14202b 0%, #0B0B0F 58%);
    font-family: "Segoe UI", Inter, system-ui, sans-serif;
    font-size: 25px;
    padding: 58px 72px;
    letter-spacing: 0.1px;
  }
  h1 { color: #ffffff; font-size: 84px; font-weight: 800; letter-spacing: -1.5px; margin: 0; }
  h2 { color: #00D4FF; font-size: 42px; font-weight: 700; margin: 0 0 6px 0; }
  h3 { color: #E8E8EC; font-size: 28px; font-weight: 600; }
  strong { color: #00D4FF; }
  em { color: #A855F7; font-style: normal; font-weight: 600; }
  ul, ol { line-height: 1.45; }
  li { margin: 9px 0; }
  blockquote { border-left: 3px solid #00D4FF; background: rgba(0,212,255,0.08);
    padding: 10px 20px; border-radius: 8px; color: #ffffff; font-style: normal; }
  .en { color: #6F8294; font-size: 0.66em; font-style: italic; font-weight: 400; display: block; margin-bottom: 18px; }
  .key { color: #ffffff; background: rgba(0,212,255,0.10); border-left: 3px solid #00D4FF;
    padding: 12px 18px; border-radius: 8px; margin-top: 16px; font-size: 0.92em; }
  .key .en { display: inline; font-size: 0.85em; color: #8FA7B8; }
  .dim { color: #8A8A95; }
  section::after { color: #46505c; font-size: 15px; font-weight: 600; }
  section.lead { text-align: center;
    background: radial-gradient(100% 110% at 50% -10%, #16263340 0%, #0B0B0F 62%); }
  section.lead h1 { font-size: 132px; letter-spacing: -3px;
    text-shadow: 0 0 60px rgba(0,212,255,0.35); }
  section.lead h2 { color: #E8E8EC; font-weight: 600; font-size: 38px; margin-top: 18px; }
  section.lead .en { font-size: 0.55em; text-align: center; }
---

<!-- _class: lead -->
<!-- _paginate: false -->

# KALI

## Скажи — и получи личного ИИ на своём железе. Поделись им, как видео.
<span class="en">Say it — get a personal AI on your own machine. Share it like a video.</span>

**Голосовой создатель ИИ-агентов для непрограммистов** · *Voice-first AI agent creator*

---

## Проблема
<span class="en">The problem</span>

- Непрограммист 30+ — **строитель, врач, таксист** — тонет в рутине.
- Каждый инструмент автоматизации требует **кода или настройки**.
- Гиганты строят ИИ для **разработчиков в облаке** — не для него.

<div class="key">Обычный человек не может автоматизировать свою жизнь — всё требует кода.
<span class="en">Non-coders can't automate their lives — every tool needs code.</span></div>

---

## Решение
<span class="en">The solution — the wedge</span>

![bg right:34% fit](assets/01-dashboard.png)

Голос → рабочий приватный агент. **Локально. Без кода. За 3 минуты.**

- Говоришь, что нужно
- Джарвис **строит** агента и **сам проверяет** его
- Запускает на **твоём железе**
- **Помнит** тебя

<div class="key">Voice in → a working, private agent. Local. No code.</div>

---

## Это работает сегодня
<span class="en">Real today — not a promise</span>

![bg right:34% fit](assets/02-store.png)

- Голос RU **вход и выход** на локальном GPU
- **Создание агента голосом** → деплой на диск
- Магазин помощников, **честные статусы**
- **Локальная память** — данные на твоей машине

<span class="dim">Desktop — основной, GPU-голос. Mobile — компаньон (на скринах). Оба реальны.</span>

---

## Стратегия: ров — на краях
<span class="en">The moat is the edges, not the model</span>

Статичная ОС → **генеративная ОС**: «скажи, что хочешь — система соберёт».

- **Непрог-голос** — единственный интерфейс для строителя/врача
- **Локальное доверие** — данные не уходят в облако
- **UGC** — дистрибуция внутри продукта

<div class="key">Модель — commodity, сменная. Мы не воюем с OpenAI на моделях — мы их используем.
<span class="en">The model is a commodity. The edges are the moat.</span></div>

---

## Рост: петля UGC
<span class="en">Growth = the loop, not the ad budget</span>

![bg right:34% fit](assets/03-share-qr.png)

Создал голосом → **ролик / ссылка** → друг сканирует **QR** → ставит в один тап → строит свой.

- Дистрибуция живёт **внутри продукта**
- Пользователи приводят пользователей
- **Без рекламного бюджета**

<div class="key">Distribution lives inside the product. Users bring users.</div>

---

## Делишься, как видео
<span class="en">Share like a video — already built</span>

![bg right:34% fit](assets/04-share-sheet.png)

Нативный share sheet → **TikTok / Instagram / YouTube** под своим аккаунтом.

- Без OAuth-интеграций платформ — **ОС делает всю работу**
- Агент «путешествует» внутри ссылки/QR — ставится без сервера

<span class="dim">На скрине — реальное системное меню «Поделиться». Не макет.</span>

---

## Почему сейчас
<span class="en">Why now</span>

Модели **коммодитизируются** → ценность уходит с модели на **края**: доверие, дистрибуция, интерфейс для обычных людей.

Три «ручки» едут вперёд **без переписывания**:

- облако → **локаль**
- описания → **код**
- приложение → **самособирающаяся оболочка**

<div class="key">Value moves off the model, onto the edges. KALI is built to ride that curve.</div>

---

## Будущее
<span class="en">The North Star — one path, no rewrite</span>

Та же архитектура едет по лесенке:

- **A** — приложение сегодня (голос + магазин)
- **B** — интерфейс **сам собирается** под задачу
- **C** — выделенное **железо** («Iron Man»)

<span class="dim">Ближайший продукт — «скажи, получи агента, поделись» — стоит на том, что уже работает.</span>

<div class="key">Same path, no rewrite: app → self-composing UI → device.</div>

---

## Честно о трекшне
<span class="en">Honest traction — strong demo ≠ PMF</span>

Сильное демо + работающий продукт. **PMF доказываем удержанием** в закрытой бете.

Воронка, которую меряем:

- **Активация** — % создавших ≥1 агента голосом
- **Удержание** — возврат на 7 / 30 день
- **K-фактор** — % поделившихся → друзья установили

<span class="dim">Не считаем успехом: установка без активации; всплеск от друзей вместо органики.</span>

---

## Почему мы
<span class="en">Why us</span>

- Соло-основатель = **оркестратор AI-агентов**. Продукт уровня команды — за месяцы. *Капитал-эффективность.*
- Дисциплина: **written scope + анти-пивот** (не лезем на dev/design-поляну).
- Архитектура (**Rust-ядро, generative-OS, сменная модель**) заложена под масштаб.

<div class="key">Solo founder orchestrating AI — a team-level product in months.</div>

---

<!-- _class: lead -->

## Запрос
<span class="en">The ask</span>

### __[сумма]__ на бету, команду и железо — до __[майлстоунов]__

<br>

**«Скажи — получи личного ИИ. Поделись им, как видео.»**
<span class="en">"Speak — get a personal AI. Share it like a video."</span>
