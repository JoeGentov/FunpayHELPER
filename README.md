# FunPay Helper — GUI + Парс активных продаж и лотов + Автовыдача в одном JSON

Быстрый старт без python и зависимостей - [БЫСТРЫЙ СТАРТ](https://github.com/JoeGentov/FunpayHELPER/issues/1)

## Что внутри
- `funpay_helper.py` — основной GUI (PySide6). Монокром, закругления, анимация, вкладки:
  - **Настройки** — токен, приветствие, фильтр, почта/пароль, запуск слушателей.
  - **Консоль** — вывод логов.
  - **Оповещения** — Discord/Telegram.
  - **Магазин** — *НОВОЕ*: парс активных **продаж** и **лотов**, просмотр таблицей, экспорт в `autodelivery_items.json`.
- `store_fetcher.py` — работа с FunPayAPI: получение активных продаж и активных лотов.
- `styles.qss` — чуть более аккуратные стили (по‑прежнему ч/б).
- `requirements.txt` — зависимости.
- `autodelivery_items.json` — общий файл для автовыдачи (создаётся/перезаписывается из вкладки «Магазин»).
  
## Запуск
```bash
pip install -r requirements.txt
python funpay_helper.py
```
> Если у вас уже установлен `FunPayAPI`, разрешается просто: `pip install PySide6 requests`

- Экспорт для автовыдачи — `autodelivery_items.json` (в корне проекта).

## Схема `autodelivery_items.json`
```json
[
  {
    "lot_id": 123456,
    "title": "Мой товар",
    "price": 59.0,
    "stock": 10,
    "subcategory": "Roblox > Robux",
    "delivery_text": "Почта: ...\nПароль: ..."
  }
]
```
