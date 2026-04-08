import os
import html
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def select_articles_via_telegram(articles: list[dict]) -> list[dict]:
    try:
        if not articles:
            return []

        selected: set[int] = set()
        chosen_articles: list[dict] = []

        # text shows above the buttons
        def build_prompt_text() -> str:
            try:
                article_lines = []
                for i, article in enumerate(articles):
                    title = article.get("title")
                    
                    # remove the name of the source
                    if title and "-" in title:
                        final_title = title[:title.rfind("-")].strip()
                    else:
                        final_title = title
                    
                    # get the url and escape it for HTML                        
                    url = article.get("url", "")
                    safe_title = html.escape(final_title)
                    safe_url = html.escape(url, quote=True)

                    # make a clickable link to the news
                    if safe_url:
                        article_lines.append(f"{i + 1}. {safe_title} - <a href=\"{safe_url}\">Read here</a>\n")
                    else:
                        article_lines.append(f"{i + 1}. {safe_title}\n")

                lines = [
                    "📰 Daily AI News Curator",
                    "",
                    "Review the stories below and tap to select the ones you want to keep.",
                    "Use Select All or Clear when needed, then press Save & Finish.",
                    "",
                    f"📚 Total stories: {len(articles)}\n",
                    *article_lines,
                ]
                return "\n".join(lines)
            except Exception as e:
                print(e)
                return "No articles available."

        # make all buttons
        def build_keyboard() -> InlineKeyboardMarkup:
            try:
                buttons = []
                for i, article in enumerate(articles):
                    title = article.get("title")
                    final_title = title[:title.rfind("-")].strip() if title and "-" in title else title
                    preview = (final_title[:28].rstrip() + "...") if len(final_title) > 31 else final_title
                    label = f"{i + 1}. {preview}"
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
            except Exception as e:
                print(e)
                return InlineKeyboardMarkup([])

        # initialize the bot-session
        async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
                selected.clear()
                await update.message.reply_text(
                    build_prompt_text(),
                    reply_markup=build_keyboard(),
                    parse_mode="HTML",
                )
            except Exception as e:
                print(e)

        # auto /start the bot
        async def send_selection_prompt(app: Application):
            try:
                selected.clear()
                await app.bot.send_message(
                    chat_id=CHAT_ID,
                    text=build_prompt_text(),
                    reply_markup=build_keyboard(),
                    parse_mode="HTML",
                )
                print("Auto selection prompt sent")
            except Exception as e:
                print(e)

        # button logic
        async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
            try:
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
            except Exception as e:
                print(e)

        # bot config/start
        app = Application.builder().token(BOT_TOKEN).post_init(send_selection_prompt).build()
        app.add_handler(CommandHandler("start", start))
        app.add_handler(CallbackQueryHandler(handle_button))

        print("Bot running")
        app.run_polling() # keep the bot running

        return chosen_articles
    except Exception as e:
        print(e)
        return []