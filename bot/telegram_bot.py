import os
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def select_articles_via_telegram(articles: list[dict]) -> list[dict]:
    if not articles:
        return []

    selected: set[int] = set()
    chosen_articles: list[dict] = []

    # truncate the title if overflowing
    def truncate_title(title: str, max_len: int = 46) -> str:
        if len(title) <= max_len:
            return title
        return title[: max_len - 3].rstrip() + "..."

    # text shows above the buttons
    def build_prompt_text() -> str:
        lines = [
            "📰 Daily AI News Curator",
            "",
            "Review the stories below and tap to select the ones you want to keep.",
            "Use Select All or Clear when needed, then press Save & Finish.",
            "",
            f"📚 Total stories: {len(articles)}",
        ]
        return "\n".join(lines)

    # make all buttons
    def build_keyboard() -> InlineKeyboardMarkup:
        buttons = []
        for i, article in enumerate(articles):
            title = truncate_title(article.get("title", f"Article {i + 1}"))
            label = f"{i + 1:02d}. {title}"
            if i in selected:
                label = f"{label}  ✅"
            buttons.append([InlineKeyboardButton(label, callback_data=f"toggle:{i}")])

        buttons.append(
            [
                InlineKeyboardButton("✅ Select All", callback_data="select_all"),
                InlineKeyboardButton("🧹 Clear", callback_data="clear_all"),
            ]
        )
        buttons.append([InlineKeyboardButton("🚀 Save & Finish", callback_data="done")])
        return InlineKeyboardMarkup(buttons)

    # initialize the bot-session
    async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
        selected.clear()
        await update.message.reply_text(
            build_prompt_text(),
            reply_markup=build_keyboard(),
        )

    # auto /start the bot
    async def send_selection_prompt(app: Application):
        selected.clear()
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=build_prompt_text(),
            reply_markup=build_keyboard(),
        )
        print("Auto selection prompt sent")

    # button logic
    async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if query.data == "done":
            chosen = [articles[i] for i in sorted(selected)]
            chosen_articles.clear()
            chosen_articles.extend(chosen)

            titles = "\n".join(f"• {a.get('title', 'Untitled')}" for a in chosen)
            if chosen:
                await query.edit_message_text(
                    f"🎉 Saved {len(chosen)} curated articles.\n\n{titles}\n\nBot session complete."
                )
            else:
                await query.edit_message_text(
                    "ℹ️ No articles were selected.\n\nBot session complete."
                )

            context.application.stop_running()
            return

        if query.data == "select_all":
            selected.update(range(len(articles)))
            await query.edit_message_reply_markup(reply_markup=build_keyboard())
            return

        if query.data == "clear_all":
            selected.clear()
            await query.edit_message_reply_markup(reply_markup=build_keyboard())
            return

        index = int(query.data.split(":", 1)[1])
        if index in selected:
            selected.discard(index)
        else:
            selected.add(index)
        await query.edit_message_reply_markup(reply_markup=build_keyboard())

    # bot config/start
    app = Application.builder().token(BOT_TOKEN).post_init(send_selection_prompt).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(handle_button))

    print("Bot running")
    app.run_polling() # keep the bot running
    
    return chosen_articles