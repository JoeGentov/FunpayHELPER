# store_fetcher.py
from typing import List
import json

class Lot:
    def __init__(self, data: dict):
        self.lot_id = data.get("lot_id")
        self.title = data.get("title")
        self.price = data.get("price")
        self.stock = data.get("stock")
        self.subcategory = data.get("subcategory")
        self.delivery_text = data.get("delivery_text")

def get_active_lots(acc, log) -> List[dict]:
    """
    Получает активные лоты пользователя, учитывая разные версии FunPayAPI.
    :param acc: Account объект
    :param log: функция логирования
    :return: список словарей с лотами
    """
    lots = []
    profile = None
    method_used = None

    try:
        # Попробуем get_self()
        if hasattr(acc, "get_self"):
            profile = acc.get_self()
            method_used = "get_self"
        # Если нет — get_profile()
        elif hasattr(acc, "get_profile"):
            profile = acc.get_profile()
            method_used = "get_profile"
        # Если нет — get_user(acc.id)
        elif hasattr(acc, "get_user"):
            profile = acc.get_user(acc.id)
            method_used = "get_user(acc.id)"
        else:
            log("Не удалось получить профиль пользователя (нет методов get_self/get_profile/get_user)")
            return []

        log(f"[store] Профиль получен через {method_used}")
        if not hasattr(profile, "get_lots"):
            log("[store] Профиль не имеет метода get_lots()")
            return []

        raw_lots = profile.get_lots()
        for lot in raw_lots:
            data = {
                "lot_id": getattr(lot, "id", None),
                "title": getattr(lot, "title", ""),
                "price": getattr(lot, "price", 0.0),
                "stock": getattr(lot, "stock", 0),
                "subcategory": getattr(lot, "subcategory_name", ""),
                "delivery_text": ""
            }
            lots.append(Lot(data))


    except Exception as e:
        log(f"[store] Ошибка при получении лотов: {e}")

    log(f"[store] Загружено лотов: {len(lots)}")
    return lots


def export_autodelivery_json(lots: list, path="autodelivery_items.json", delivery_template=None):
    """
    Сохраняет список лотов в JSON для автовыдачи
    :param lots: список словарей
    :param path: путь сохранения
    :param delivery_template: строка, шаблон для поля delivery_text (по умолчанию пусто)
    """
    for lot in lots:
        if delivery_template:
            lot["delivery_text"] = delivery_template
    with open(path, "w", encoding="utf-8") as f:
        json.dump(lots, f, ensure_ascii=False, indent=2)
