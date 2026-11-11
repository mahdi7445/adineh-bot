class InlineKeyboardButton:
    def __init__(self, text, callback_data=None, url=None):
        self.text, self.callback_data, self.url = text, callback_data, url
class InlineKeyboardMarkup:
    def __init__(self, rows): self.inline_keyboard = rows
class Update: ALL_TYPES = None
