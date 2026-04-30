from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def build_keyboard(buttons: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """Create a simple vertical inline keyboard."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=label, callback_data=callback_data)]
            for label, callback_data in buttons
        ]
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Main menu after onboarding is complete."""
    return build_keyboard(
        [
            ("Today advice", "menu:today"),
            ("Tomorrow advice", "menu:tomorrow"),
            ("Preferences", "menu:preferences"),
            ("Quick Requests", "menu:quick_requests"),
        ]
    )