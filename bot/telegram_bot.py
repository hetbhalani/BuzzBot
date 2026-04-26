import os
import html
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CopyTextButton
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    filters,
)
from pipelines.edit_draft_post_w_prompt import edit_draft_post_w_prompt

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

def select_articles_via_telegram(articles: list[dict], mode: str = "daily", required_count: int = 5) -> list[dict]:
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

                if mode == "weekly":
                    header = [
                        "🏆 Weekly Top 10 Review",
                        "",
                        f"Please select exactly {required_count} articles to feature in the newsletter.",
                    ]
                else:
                    header = [
                        "📰 Daily AI News Curator",
                        "",
                        "Review the stories below and tap to select the ones you want to keep.",
                    ]
                    
                lines = header + [
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
                    if mode == "weekly" and required_count and len(selected) != required_count:
                        await query.answer(f"⚠️ Please select exactly {required_count} articles! You have {len(selected)}.", 
                            show_alert=True
                        )
                        return
                        
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

WAITING_FOR_PROMPT = 1  # bot is waiting for the user to type a prompt
WAITING_FOR_EDIT = 2    # bot is waiting for the user to send back the edited post
WAITING_FOR_EDIT_CONFIRM = 3  # bot is waiting for the user to confirm the edit

# Review the draft post and decide the next move
def review_post_via_telegram(state: dict) -> dict:

    draft = state["draft_post"]
    result: dict = {}     

    def build_review_text() -> str:
        return (
            "📝 <b>Review Your Draft LinkedIn Post</b>\n\n"
            f"{html.escape(draft)}\n\n"
            "Choose an action below:"
        )

    def build_review_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🔄 Reprompt LLM", callback_data="prompt_llm"),
                InlineKeyboardButton("✏️ Edit Post",    callback_data="edit_post"),
            ],
            [
                InlineKeyboardButton("🚀 Post", callback_data="post"),
            ],
        ])

    async def send_draft(app: Application):
        await app.bot.send_message(
            chat_id=CHAT_ID,
            text=build_review_text(),
            reply_markup=build_review_keyboard(),
            parse_mode="HTML",
        )
        print("Draft sent to telegram")

    async def handle_action_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()

        if query.data == "prompt_llm":
            await query.edit_message_reply_markup(reply_markup=None) # remove buttons
            await query.message.reply_text(
                "✍️ Please type your prompt / instructions for the LLM and send it as a message:"
            )
            # move to the next state
            return WAITING_FOR_PROMPT

        if query.data == "edit_post":
            await query.edit_message_reply_markup(reply_markup=None)

            copy_keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Copy Draft", copy_text=CopyTextButton(text=draft))]
            ])

            await query.message.reply_text(
                "✏️ Tap <b>Copy Draft</b> below to copy the post to your clipboard.\n"
                "Then paste it here, make your edits, and send it back!",
                reply_markup=copy_keyboard,
                parse_mode="HTML",
            )
            return WAITING_FOR_EDIT

        if query.data == "post":
            await query.edit_message_text("✅ Post approved! Proceeding to publish...")
            result["approve_status"] = "post"
            context.application.stop_running()
            return ConversationHandler.END

    async def receive_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        user_prompt = update.message.text.strip()

        await update.message.reply_text(
            f"⚙️ Got it! Sending your prompt to the LLM...\n\n"
            f"<i>Prompt: {html.escape(user_prompt)}</i>",
            parse_mode="HTML",
        )

        # call the editing pipeline
        edited = edit_draft_post_w_prompt(
            instruction=user_prompt,
            draft_post=draft,
        )

        result["approve_status"] = "prompt_llm"
        result["user_prompt"]     = user_prompt
        result["edited_response"] = edited

        # show the edited post back to the user
        await update.message.reply_text(
            f"✅ <b>Edited Post:</b>\n\n{html.escape(edited)}",
            parse_mode="HTML",
        )

        context.application.stop_running()
        return ConversationHandler.END

    async def receive_edited_post(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        final_post = update.message.text.strip()

        context.user_data["pending_edited_post"] = final_post

        confirm_keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Confirm",   callback_data="confirm_edit"),
                InlineKeyboardButton("🔁 Re-edit",  callback_data="redo_edit"),
            ]
        ])

        await update.message.reply_text(
            f"📋 <b>Here is your edited post</b>\n\n{html.escape(final_post)}",
            reply_markup=confirm_keyboard,
            parse_mode="HTML",
        )
        return WAITING_FOR_EDIT_CONFIRM

    async def handle_edit_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        query = update.callback_query
        await query.answer()

        if query.data == "confirm_edit":
            final_post = context.user_data.get("pending_edited_post", "")
            result["approve_status"] = "edit_post"
            result["edited_response"] = final_post

            await query.edit_message_text(
                f"✅ <b>Saved! Here is your final post:</b>\n\n{html.escape(final_post)}",
                parse_mode="HTML",
            )
            context.application.stop_running()
            return ConversationHandler.END

        if query.data == "redo_edit":
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                "✍️ No problem! Please send back the updated version of the post:"
            )
            return WAITING_FOR_EDIT


    conv_handler = ConversationHandler(
        # The conversation starts when a button is pressed
        entry_points=[CallbackQueryHandler(handle_action_button)],
        states={
            # Waiting for the user to type an LLM instruction
            WAITING_FOR_PROMPT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_prompt)
            ],
            # Waiting for the user to paste their manually edited post
            WAITING_FOR_EDIT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_edited_post)
            ],
            # Waiting for the user to confirm or re-edit
            WAITING_FOR_EDIT_CONFIRM: [
                CallbackQueryHandler(handle_edit_confirmation)
            ],
        },
        fallbacks=[],
    )

    # start running the bot
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(send_draft)
        .build()
    )
    app.add_handler(conv_handler)

    print("Bot running...")
    app.run_polling()

    # merge result back into the original state and return
    return {**state, **result}
