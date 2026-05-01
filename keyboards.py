"""Build Telegram reply and inline keyboards used by onboarding, settings, and Ask flows."""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup


def build_keyboard(buttons: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Create a simple vertical inline keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=callback_data)]
            for label, callback_data in buttons
        ]
    )


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Main menu after onboarding is complete."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Today"), KeyboardButton(text="Tomorrow")],
            [KeyboardButton(text="Settings"), KeyboardButton(text="Ask")],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )


def change_settings_keyboard() -> InlineKeyboardMarkup:
    return build_keyboard([("Change settings", "settings:change")])


def wizard_location_keyboard() -> InlineKeyboardMarkup:
    return build_keyboard([
        ("Use my saved location", "wiz:loc:saved"),
        ("Other location", "wiz:loc:other"),
    ])


def wizard_day_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Today", callback_data="wiz:day:today"),
            InlineKeyboardButton(text="Tomorrow", callback_data="wiz:day:tomorrow"),
        ],
        [
            InlineKeyboardButton(text="This weekend", callback_data="wiz:day:weekend"),
            InlineKeyboardButton(text="This week", callback_data="wiz:day:week"),
        ],
        [InlineKeyboardButton(text="Specific date", callback_data="wiz:day:specific")],
    ])


def wizard_category_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="What to wear", callback_data="wiz:cat:wear"),
            InlineKeyboardButton(text="What to be aware of", callback_data="wiz:cat:aware"),
        ],
        [
            InlineKeyboardButton(text="Outdoor activities", callback_data="wiz:cat:activities"),
            InlineKeyboardButton(text="General overview", callback_data="wiz:cat:overview"),
        ],
    ])
