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
