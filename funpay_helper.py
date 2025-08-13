
# -*- coding: utf-8 -*-
"""
FunPay Helper — улучшенный GUI + парс активных продаж/лотов + экспорт одного JSON для автовыдачи.
Запуск: python funpay_helper.py
"""
from __future__ import annotations
import os, sys, json, threading, subprocess
from datetime import datetime

try:
    import FunPayAPI
    from FunPayAPI import Account, Runner, enums
except Exception:
    FunPayAPI = None
    Account = Runner = enums = None

import requests
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt
from store_fetcher import get_active_lots, export_autodelivery_json

APP_NAME = "FunPay Helper"

FILES = {
    "golden_key": "goldenkey.txt",
    "first_message": "message.txt",
    "account_name": "accountname.txt",
    "mail": "account1mail.txt",
    "password": "account1pass.txt",
    "discord_webhook": "discord_webhook.txt",
    "tg_bot_token": "telegram_token.txt",
    "tg_chat_id": "telegram_chat_id.txt",
    "autodelivery_json": "autodelivery_items.json",
}

def read_file(path: str, default: str = "") -> str:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
    except Exception:
        pass
    return default

def write_file(path: str, value: str) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(value or "")
    except Exception:
        pass

# ---------------------------- Notifications ----------------------------
class Notifier:
    def __init__(self, console_cb):
        self.console_cb = console_cb
        self.discord_webhook = read_file(FILES["discord_webhook"]) or ""
        self.tg_bot_token = read_file(FILES["tg_bot_token"]) or ""
        self.tg_chat_id = read_file(FILES["tg_chat_id"]) or ""

    def log(self, msg: str):
        if self.console_cb:
            self.console_cb(msg)

    def save(self, discord_webhook: str, tg_token: str, tg_chat_id: str):
        self.discord_webhook = discord_webhook.strip()
        self.tg_bot_token = tg_token.strip()
        self.tg_chat_id = tg_chat_id.strip()
        write_file(FILES["discord_webhook"], self.discord_webhook)
        write_file(FILES["tg_bot_token"], self.tg_bot_token)
        write_file(FILES["tg_chat_id"], self.tg_chat_id)

    def send_discord(self, content: str):
        if not self.discord_webhook:
            self.log("[Discord] Webhook URL is empty — skipped.")
            return
        try:
            r = requests.post(self.discord_webhook, json={"content": content}, timeout=10)
            if r.ok:
                self.log("[Discord] Sent.")
            else:
                self.log(f"[Discord] HTTP {r.status_code}: {r.text[:120]}")
        except Exception as e:
            self.log(f"[Discord] Error: {e}")

    def send_telegram(self, text: str):
        if not (self.tg_bot_token and self.tg_chat_id):
            self.log("[Telegram] Token or chat_id is empty — skipped.")
            return
        url = f"https://api.telegram.org/bot{self.tg_bot_token}/sendMessage"
        try:
            r = requests.post(url, data={"chat_id": self.tg_chat_id, "text": text}, timeout=10)
            if r.ok:
                self.log("[Telegram] Sent.")
            else:
                self.log(f"[Telegram] HTTP {r.status_code}: {r.text[:120]}")
        except Exception as e:
            self.log(f"[Telegram] Error: {e}")

    def broadcast(self, text: str):
        self.send_discord(text)
        self.send_telegram(text)

# ---------------------------- Animated Button ----------------------------
class AnimatedButton(QtWidgets.QPushButton):
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self._opacity_effect = QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity_effect.setOpacity(1.0)
        self.setGraphicsEffect(self._opacity_effect)
        self._anim = QtCore.QPropertyAnimation(self._opacity_effect, b"opacity", self)
        self._anim.setDuration(150)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.85)
        self.setMinimumHeight(40)

    def enterEvent(self, e):
        self._anim.setDirection(QtCore.QAbstractAnimation.Forward)
        self._anim.start()
        super().enterEvent(e)

    def leaveEvent(self, e):
        self._anim.setDirection(QtCore.QAbstractAnimation.Backward)
        self._anim.start()
        super().leaveEvent(e)

# ---------------------------- Console Widget ----------------------------
class Console(QtWidgets.QPlainTextEdit):
    def __init__(self):
        super().__init__()
        self.setReadOnly(True)
        self.setWordWrapMode(QtGui.QTextOption.NoWrap)

    @QtCore.Slot(str)
    def append_line(self, text: str):
        ts = datetime.now().strftime('%H:%M:%S')
        self.appendPlainText(f"[{ts}] {text}")
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())

# ---------------------------- Workers (как в вашей версии) ----------------------------
class ExternalScriptRunner(QtCore.QThread):
    message = QtCore.Signal(str)

    def __init__(self, script_path: str, debug_to_console: bool):
        super().__init__()
        self.script_path = script_path
        self.debug_to_console = debug_to_console
        self._proc: subprocess.Popen | None = None

    def run(self):
        if not os.path.exists(self.script_path):
            self.message.emit(f"External script not found: {self.script_path}")
            return
        self.message.emit(f"Starting external script: {os.path.basename(self.script_path)}")
        try:
            self._proc = subprocess.Popen([sys.executable, self.script_path],
                                          stdout=subprocess.PIPE,
                                          stderr=subprocess.STDOUT,
                                          text=True,
                                          bufsize=1)
            if self.debug_to_console and self._proc.stdout:
                for line in self._proc.stdout:
                    self.message.emit(line.rstrip())
            self._proc.wait()
            self.message.emit(f"External script exited with code {self._proc.returncode}")
        except Exception as e:
            self.message.emit(f"External script error: {e}")

    def stop(self):
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
            except Exception:
                pass

class FunPayWelcomeWorker(QtCore.QThread):
    message = QtCore.Signal(str)
    event_info = QtCore.Signal(str)

    def __init__(self, token: str, greeting: str, notifier: Notifier):
        super().__init__()
        self.token = token
        self.greeting = greeting
        self.notifier = notifier
        self._stop = threading.Event()

    def run(self):
        if FunPayAPI is None:
            self.message.emit("FunPayAPI not installed — install with: pip install FunPayAPI")
            return
        try:
            acc = Account(self.token).get()
            runner = Runner(acc)
            self.message.emit("Welcome listener started.")
            self.notifier.broadcast("✅ Welcome listener started")
            for event in runner.listen(requests_delay=4):
                if self._stop.is_set():
                    break
                if event.type is enums.EventTypes.NEW_MESSAGE:
                    try:
                        if hasattr(event, 'message') and getattr(event.message, 'author_id', None) != acc.id:
                            chat_id = event.message.chat_id
                            acc.send_message(chat_id, self.greeting)
                            info = f"Greeting sent to chat {chat_id}"
                            self.event_info.emit(info)
                            self.notifier.broadcast(f"💬 {info}")
                    except Exception as e:
                        self.message.emit(f"[Welcome] Error: {e}")
        except Exception as e:
            self.message.emit(f"[Welcome] Fatal: {e}")
        finally:
            self.message.emit("Welcome listener stopped.")
            self.notifier.broadcast("⛔ Welcome listener stopped")

    def stop(self):
        self._stop.set()

class FunPayAutoDeliverWorker(QtCore.QThread):
    message = QtCore.Signal(str)
    event_info = QtCore.Signal(str)

    def __init__(self, token: str, account_name_filter: str, mail: str, password: str, notifier: Notifier):
        super().__init__()
        self.token = token
        self.account_name_filter = account_name_filter
        self.mail = mail
        self.password = password
        self.notifier = notifier
        self._stop = threading.Event()

    def _send_autodelivery_for_order(self, acc, order, buyer_name: str):
        """
        Пример: пытаемся найти запись в autodelivery_items.json по subcategory/title,
        иначе — шлём дефолт из настроек.
        """
        delivery_text = ""
        try:
            if os.path.exists(FILES["autodelivery_json"]):
                with open(FILES["autodelivery_json"], "r", encoding="utf-8") as f:
                    data = json.load(f)
                title = getattr(order, "short_description", getattr(order, "description", "")) or ""
                subc = getattr(order, "subcategory_name", getattr(getattr(order, "subcategory", None), "name", ""))
                # простая эвристика: точное совпадение title либо подкатегории
                for it in data:
                    if it.get("title") == title or it.get("subcategory") == subc:
                        delivery_text = it.get("delivery_text") or ""
                        break
        except Exception as e:
            self.message.emit(f"[AutoDeliver] JSON read error: {e}")

        if not delivery_text:
            delivery_text = f"Привет, {buyer_name}!\nВот твой аккаунт:\nПочта: {self.mail}\nПароль: {self.password}"

        try:
            # попытка через order.chat_id, иначе через поиск чата
            chat_id = getattr(order, "chat_id", None)
            if chat_id is None and hasattr(acc, 'get_chat_by_name'):
                try:
                    chat = acc.get_chat_by_name(buyer_name, True)
                    chat_id = getattr(chat, "id", None)
                except Exception:
                    chat_id = None
            if chat_id is not None:
                acc.send_message(chat_id, delivery_text)
                return True, f"Credentials sent to {buyer_name} (chat {chat_id})"
        except Exception as e:
            return False, f"[AutoDeliver] send error: {e}"
        return False, f"Order from {buyer_name} matched, but no chat found."

    def run(self):
        if FunPayAPI is None:
            self.message.emit("FunPayAPI not installed — install with: pip install FunPayAPI")
            return
        try:
            acc = Account(self.token).get()
            runner = Runner(acc)
            self.message.emit("Auto-delivery listener started.")
            self.notifier.broadcast("✅ Auto-delivery listener started")
            for event in runner.listen(requests_delay=4):
                if self._stop.is_set():
                    break
                if event.type is enums.EventTypes.NEW_ORDER:
                    try:
                        order = event.order
                        desc = getattr(order, 'description', '') or ''
                        buyer = getattr(order, 'buyer_username', 'buyer')
                        if self.account_name_filter and self.account_name_filter not in desc:
                            continue
                        ok, info = self._send_autodelivery_for_order(acc, order, buyer)
                        self.event_info.emit(info)
                        self.notifier.broadcast(("📦 " if ok else "⚠️ ") + info)
                    except Exception as e:
                        self.message.emit(f"[AutoDeliver] Error: {e}")
        except Exception as e:
            self.message.emit(f"[AutoDeliver] Fatal: {e}")
        finally:
            self.message.emit("Auto-delivery listener stopped.")
            self.notifier.broadcast("⛔ Auto-delivery listener stopped")

    def stop(self):
        self._stop.set()

# ---------------------------- Main Window ----------------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1100, 720)

        # Стили
        qss_path = os.path.join(os.path.dirname(__file__), "styles.qss")
        if os.path.exists(qss_path):
            with open(qss_path, "r", encoding="utf-8") as f:
                self.setStyleSheet(f.read())

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        vbox = QtWidgets.QVBoxLayout(central)
        vbox.setContentsMargins(16, 16, 16, 16)
        vbox.setSpacing(12)

        self.tabs = QtWidgets.QTabWidget()
        vbox.addWidget(self.tabs)

        self.tab_settings = QtWidgets.QWidget()
        self.tab_console = QtWidgets.QWidget()
        self.tab_notifications = QtWidgets.QWidget()
        self.tab_store = QtWidgets.QWidget()  # Новая вкладка

        self.tabs.addTab(self.tab_settings, "Настройки / Settings")
        self.tabs.addTab(self.tab_console, "Консоль / Console")
        self.tabs.addTab(self.tab_notifications, "Оповещения / Alerts")
        self.tabs.addTab(self.tab_store, "Магазин / Store")

        self._build_settings_tab()
        self._build_console_tab()
        self._build_notifications_tab()
        self._build_store_tab()

        # State
        self.notifier = Notifier(self.console.append_line)
        self.welcome_worker: FunPayWelcomeWorker | None = None
        self.autodeliver_worker: FunPayAutoDeliverWorker | None = None
        self.ext_runner: ExternalScriptRunner | None = None

        self._load_initial_values()

    # ---------- UI Builders ----------
    def _build_settings_tab(self):
        layout = QtWidgets.QGridLayout(self.tab_settings)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(10)

        # Inputs
        self.ed_token = QtWidgets.QLineEdit()
        self.ed_first_message = QtWidgets.QTextEdit()
        self.ed_account_name = QtWidgets.QLineEdit()
        self.ed_mail = QtWidgets.QLineEdit()
        self.ed_password = QtWidgets.QLineEdit()
        self.ed_password.setEchoMode(QtWidgets.QLineEdit.Password)

        # Labels
        layout.addWidget(QtWidgets.QLabel("FunPay TOKEN (goldenkey.txt):"), 0, 0)
        layout.addWidget(self.ed_token, 0, 1)

        layout.addWidget(QtWidgets.QLabel("Приветственное сообщение / Greeting (message.txt):"), 1, 0)
        layout.addWidget(self.ed_first_message, 1, 1)

        layout.addWidget(QtWidgets.QLabel("Это бесплатная программа сделанная JoeGentov, если вы заплатили деньги, то вас обманули"), 2, 0)



        # Controls
        self.btn_save = AnimatedButton("Сохранить / Save")
        self.btn_start_welcome = AnimatedButton("▶ Приветствия / Welcome")
        self.btn_start_auto = AnimatedButton("▶ Автовыдача / Auto-delivery")
        self.btn_stop_all = AnimatedButton("■ Стоп всё / Stop all")

        self.btn_save.clicked.connect(self._save_settings)
        self.btn_start_welcome.clicked.connect(self._start_welcome)
        self.btn_start_auto.clicked.connect(self._start_auto)
        self.btn_stop_all.clicked.connect(self._stop_all)

        row = 5
        layout.addWidget(self.btn_save, row, 0)
        layout.addWidget(self.btn_start_welcome, row, 1)
        row += 1
        layout.addWidget(self.btn_start_auto, row, 1)
        layout.addWidget(self.btn_stop_all, row, 0)

        # Script group
        row += 1
        grp = QtWidgets.QGroupBox("Загрузка скрипта с отладкой / External script with debug")
        gl = QtWidgets.QGridLayout(grp)
        self.script_path_edit = QtWidgets.QLineEdit()
        self.script_path_btn = AnimatedButton("Выбрать .py… / Browse…")
        self.chk_debug_output = QtWidgets.QCheckBox("Отладка в консоли / Debug to console")
        self.btn_run_script = AnimatedButton("▶ Запустить / Run")
        self.btn_stop_script = AnimatedButton("■ Остановить / Stop")

        self.script_path_btn.clicked.connect(self._choose_script)
        self.btn_run_script.clicked.connect(self._run_external_script)
        self.btn_stop_script.clicked.connect(self._stop_external_script)

        gl.addWidget(QtWidgets.QLabel("Путь к .py:"), 0, 0)
        gl.addWidget(self.script_path_edit, 0, 1)
        gl.addWidget(self.script_path_btn, 0, 2)
        gl.addWidget(self.chk_debug_output, 1, 1)
        gl.addWidget(self.btn_run_script, 2, 1)
        gl.addWidget(self.btn_stop_script, 2, 2)
        layout.addWidget(grp, row, 0, 1, 2)

    def _build_console_tab(self):
        v = QtWidgets.QVBoxLayout(self.tab_console)
        v.setContentsMargins(16, 16, 16, 16)
        self.console = Console()
        v.addWidget(self.console)
        h = QtWidgets.QHBoxLayout()
        self.btn_clear = AnimatedButton("Очистить / Clear")
        self.btn_copy = AnimatedButton("Скопировать / Copy")
        self.btn_clear.clicked.connect(lambda: self.console.setPlainText(""))
        self.btn_copy.clicked.connect(self._copy_console)
        h.addWidget(self.btn_clear)
        h.addWidget(self.btn_copy)
        h.addStretch(1)
        v.addLayout(h)

    def _build_notifications_tab(self):
        layout = QtWidgets.QGridLayout(self.tab_notifications)
        layout.setContentsMargins(16, 16, 16, 16)
        self.ed_webhook = QtWidgets.QLineEdit(read_file(FILES["discord_webhook"]))
        self.ed_tg_token = QtWidgets.QLineEdit(read_file(FILES["tg_bot_token"]))
        self.ed_tg_chat = QtWidgets.QLineEdit(read_file(FILES["tg_chat_id"]))

        layout.addWidget(QtWidgets.QLabel("Discord Webhook URL:"), 0, 0)
        layout.addWidget(self.ed_webhook, 0, 1)
        layout.addWidget(QtWidgets.QLabel("Telegram Bot Token:"), 1, 0)
        layout.addWidget(self.ed_tg_token, 1, 1)
        layout.addWidget(QtWidgets.QLabel("Telegram Chat ID:"), 2, 0)
        layout.addWidget(self.ed_tg_chat, 2, 1)

        self.btn_save_notif = AnimatedButton("Сохранить / Save")
        self.btn_test_notif = AnimatedButton("Тест отправки / Test")
        layout.addWidget(self.btn_save_notif, 3, 0)
        layout.addWidget(self.btn_test_notif, 3, 1)

        self.btn_save_notif.clicked.connect(self._save_notifications)
        self.btn_test_notif.clicked.connect(self._test_notifications)

    def _build_store_tab(self):
        layout = QtWidgets.QVBoxLayout(self.tab_store)
        layout.setContentsMargins(16, 16, 16, 16)

        top = QtWidgets.QHBoxLayout()
        self.btn_load_sales = AnimatedButton("⬇ Активные продажи")
        self.btn_load_lots = AnimatedButton("⬇ Активные лоты")
        self.btn_export_json = AnimatedButton("💾 Экспорт JSON для автовыдачи")
        self.ed_json_path = QtWidgets.QLineEdit(FILES["autodelivery_json"])
        self.btn_browse_json = AnimatedButton("…")

        top.addWidget(self.btn_load_sales)
        top.addWidget(self.btn_load_lots)
        top.addStretch(1)
        top.addWidget(QtWidgets.QLabel("Путь JSON:"))
        top.addWidget(self.ed_json_path)
        top.addWidget(self.btn_browse_json)
        top.addWidget(self.btn_export_json)
        layout.addLayout(top)

        # Таблица
        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Тип", "ID/lot_id", "Название", "Цена", "Остаток", "delivery_text"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        layout.addWidget(self.table)

        # Подсказка
        self.hint = QtWidgets.QLabel("Подсказка: вы можете отредактировать столбец delivery_text перед экспортом.")
        layout.addWidget(self.hint)

        # Сигналы
        self.btn_load_sales.clicked.connect(self._load_active_sales)
        self.btn_load_lots.clicked.connect(self._load_active_lots)
        self.btn_export_json.clicked.connect(self._export_json)
        self.btn_browse_json.clicked.connect(self._browse_json)

    # ---------- Helpers ----------
    def _load_initial_values(self):
        self.ed_token.setText(read_file(FILES["golden_key"]))
        self.ed_first_message.setPlainText(read_file(FILES["first_message"]))
        self.ed_account_name.setText(read_file(FILES["account_name"]))
        self.ed_mail.setText(read_file(FILES["mail"]))
        self.ed_password.setText(read_file(FILES["password"]))

    def _save_settings(self):
        write_file(FILES["golden_key"], self.ed_token.text())
        write_file(FILES["first_message"], self.ed_first_message.toPlainText())
        write_file(FILES["account_name"], self.ed_account_name.text())
        write_file(FILES["mail"], self.ed_mail.text())
        write_file(FILES["password"], self.ed_password.text())
        self.console.append_line("Настройки сохранены / Settings saved.")

    def _save_notifications(self):
        self.notifier.save(self.ed_webhook.text(), self.ed_tg_token.text(), self.ed_tg_chat.text())
        self.console.append_line("Оповещения сохранены / Alerts saved.")

    def _test_notifications(self):
        text = f"Test from {APP_NAME} at {datetime.now().isoformat(timespec='seconds')}"
        self.notifier.broadcast(text)

    def _copy_console(self):
        QtWidgets.QApplication.clipboard().setText(self.console.toPlainText())
        self.console.append_line("Console copied to clipboard.")

    # ---------- Store (sales & lots) ----------
    def _set_rows(self, rows):
        self.table.setRowCount(0)
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            for c, val in enumerate(r):
                item = QtWidgets.QTableWidgetItem(val if isinstance(val, str) else ("" if val is None else str(val)))
                if c != 5:  # delivery_text колонка — редактируемая; остальное read-only
                    flags = item.flags()
                    item.setFlags(flags & ~Qt.ItemIsEditable)
                self.table.setItem(row, c, item)

    def _load_active_sales(self):
        token = self.ed_token.text().strip()
        if not token:
            self.console.append_line("Введите токен / Provide token.")
            return
        try:
            if FunPayAPI is None:
                raise RuntimeError("FunPayAPI not installed")
            acc = Account(token).get()
            sales = get_active_sales(acc, self.console.append_line)
            if not sales:
                self.console.append_line("Список активных продаж пуст или недоступен в вашей версии API.")
            rows = []
            for s in sales:
                rows.append(["sale", s.id, s.description, s.price, s.amount, ""])
            self._set_rows(rows)
            self.console.append_line(f"Загружено продаж: {len(rows)}")
        except Exception as e:
            self.console.append_line(f"[load_sales] {e}")

    def _load_active_lots(self):
        token = self.ed_token.text().strip()
        if not token:
            self.console.append_line("Введите токен / Provide token.")
            return
        try:
            if FunPayAPI is None:
                raise RuntimeError("FunPayAPI not installed")
            acc = Account(token).get()
            lots = get_active_lots(acc, self.console.append_line)
            if not lots:
                self.console.append_line("Активные лоты не найдены.")
            rows = []
            for l in lots:
                rows.append(["lot", l.lot_id, l.title, l.price, l.stock, ""])
            self._set_rows(rows)
            self.console.append_line(f"Загружено лотов: {len(rows)}")
        except Exception as e:
            self.console.append_line(f"[load_lots] {e}")

    def _browse_json(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Сохранить JSON", FILES["autodelivery_json"], "JSON (*.json)")
        if path:
            self.ed_json_path.setText(path)

    def _export_json(self):
        path = self.ed_json_path.text().strip() or FILES["autodelivery_json"]
        rows = self.table.rowCount()
        lots = []
        for i in range(rows):
            row_type = self.table.item(i, 0).text()
            if row_type != "lot":
                continue
            lot_id = int(self.table.item(i, 1).text())
            title = self.table.item(i, 2).text()
            price = self.table.item(i, 3).text()
            try:
                price = float(price) if price else None
            except Exception:
                price = None
            stock = self.table.item(i, 4).text()
            try:
                stock = int(stock) if stock else None
            except Exception:
                stock = None
            delivery_text = self.table.item(i, 5).text() if self.table.item(i, 5) else ""
            lots.append({
                "lot_id": lot_id, "title": title, "price": price, "stock": stock,
                "subcategory": None, "delivery_text": delivery_text
            })
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(lots, f, ensure_ascii=False, indent=2)
            self.console.append_line(f"Экспортировано в {path} ({len(lots)} поз.)")
        except Exception as e:
            self.console.append_line(f"[export_json] {e}")

    # ---------- Listeners control ----------
    def _start_welcome(self):
        token = self.ed_token.text().strip()
        greeting = self.ed_first_message.toPlainText().strip()
        if not token or not greeting:
            self.console.append_line("Введите токен и приветствие / Provide token and greeting.")
            return
        self._stop_welcome()
        self.welcome_worker = FunPayWelcomeWorker(token, greeting, self.notifier)
        self.welcome_worker.message.connect(self.console.append_line)
        self.welcome_worker.event_info.connect(self.console.append_line)
        self.welcome_worker.start()

    def _start_auto(self):
        token = self.ed_token.text().strip()
        name_filter = self.ed_account_name.text().strip()
        mail = self.ed_mail.text().strip()
        pwd = self.ed_password.text().strip()
        if not token or not mail or not pwd:
            self.console.append_line("Введите токен, почту и пароль / Provide token, mail, password.")
            return
        self._stop_auto()
        self.autodeliver_worker = FunPayAutoDeliverWorker(token, name_filter, mail, pwd, self.notifier)
        self.autodeliver_worker.message.connect(self.console.append_line)
        self.autodeliver_worker.event_info.connect(self.console.append_line)
        self.autodeliver_worker.start()

    def _stop_welcome(self):
        if self.welcome_worker:
            self.welcome_worker.stop()
            self.welcome_worker.wait(1000)
            self.welcome_worker = None

    def _stop_auto(self):
        if self.autodeliver_worker:
            self.autodeliver_worker.stop()
            self.autodeliver_worker.wait(1000)
            self.autodeliver_worker = None

    def _stop_all(self):
        self._stop_welcome()
        self._stop_auto()
        self._stop_external_script()
        self.console.append_line("Все процессы остановлены / All processes stopped.")

    # ---------- External script ----------
    def _choose_script(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Выберите .py", os.getcwd(), "Python (*.py)")
        if path:
            self.script_path_edit.setText(path)

    def _run_external_script(self):
        path = self.script_path_edit.text().strip()
        debug = self.chk_debug_output.isChecked()
        if not path:
            self.console.append_line("Укажите путь к скрипту / Choose a script path.")
            return
        self._stop_external_script()
        self.ext_runner = ExternalScriptRunner(path, debug)
        self.ext_runner.message.connect(self.console.append_line)
        self.ext_runner.start()

    def _stop_external_script(self):
        if self.ext_runner:
            self.ext_runner.stop()
            self.ext_runner.wait(500)
            self.ext_runner = None

    # ---------- Close ----------
    def closeEvent(self, e: QtGui.QCloseEvent) -> None:
        self._stop_all()
        return super().closeEvent(e)

# ---------------------------- Main ----------------------------
def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    QtWidgets.QApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)

    w = MainWindow()
    w.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
