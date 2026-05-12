import os
import asyncio
import html
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from pipelines.edit_draft_post_w_prompt import edit_draft_post_w_prompt

load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

import redis as redis_lib
from langgraph.types import Command

try:
    from langgraph.errors import GraphInterrupt
except ImportError:
    try:
        from langgraph.types import GraphInterrupt  # some versions export here
    except ImportError:
        GraphInterrupt = Exception  # fallback

_executor = ThreadPoolExecutor(max_workers=2)


def _redis():
    return redis_lib.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))


def save_active_session(mode: str, thread_id: str):
    _redis().set("buzzbot:active_session", json.dumps({"mode": mode, "thread_id": thread_id}))


def _clear_active_session():
    _redis().delete("buzzbot:active_session")


def _get_active_session():
    data = _redis().get("buzzbot:active_session")
    return json.loads(data) if data else None


# ─── Article Selection (daily + weekly, unchanged pattern) ────────────────────

def send_selection_prompt(articles: list[dict], mode: str = "daily"):
    required_count = 5 if mode == "weekly" else 0

    r = _redis()
    r.set(f"buzzbot:{mode}_articles", json.dumps(articles))

    def build_prompt_text():
        article_lines = []
        for i, article in enumerate(articles):
            title = article.get("title")
            final_title = title[:title.rfind("-")].strip() if title and "-" in title else title
            url = article.get("url", "")
            safe_title = html.escape(final_title)
            safe_url = html.escape(url, quote=True)
            if safe_url:
                article_lines.append(f'{i + 1}. {safe_title} - <a href="{safe_url}">Read here</a>\n')
            else:
                article_lines.append(f"{i + 1}. {safe_title}\n")

        if mode == "weekly":
            header = ["🏆 Weekly Top 10 Review", "", f"Please select exactly {required_count} articles to feature in the newsletter."]
        else:
            header = ["📰 Daily AI News Curator", "", "Review the stories below and tap to select the ones you want to keep."]

        return "\n".join(header + ["", f"📚 Total stories: {len(articles)}\n", *article_lines])

    def build_keyboard(selected_set):
        buttons = []
        for i, article in enumerate(articles):
            title = article.get("title")
            final_title = title[:title.rfind("-")].strip() if title and "-" in title else title
            preview = (final_title[:28].rstrip() + "...") if len(final_title) > 31 else final_title
            label = f"{i + 1}. {preview}  ✅" if i in selected_set else f"{i + 1}. {preview}"
            buttons.append([InlineKeyboardButton(label, callback_data=f"toggle:{i}")])
        buttons.append([
            InlineKeyboardButton("✅ Select All", callback_data="select_all"),
            InlineKeyboardButton("🧹 Clear", callback_data="clear_all"),
        ])
        buttons.append([InlineKeyboardButton("🚀 Save & Finish", callback_data="done")])
        return InlineKeyboardMarkup(buttons)

    async def _send():
        from telegram import Bot
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=CHAT_ID,
            text=build_prompt_text(),
            reply_markup=build_keyboard(set()),
            parse_mode="HTML",
        )
        print(f"[Telegram] {mode} selection prompt sent")

    def _run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_send())
        loop.close()

    t = threading.Thread(target=_run_in_thread)
    t.start()
    t.join()


# ─── Draft review prompt (one-shot, non-blocking — replaces review_post_via_telegram) ───

def send_review_prompt(draft: str, thread_id: str):
    """Send the draft to Telegram with Post / Edit / Reprompt buttons.
    Stores the draft in Redis so the persistent bot can read it back.
    Returns immediately — does NOT block waiting for a response."""

    r = _redis()
    r.set("buzzbot:weekly_review_draft", draft)
    save_active_session("weekly_review", thread_id)

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

    async def _send():
        from telegram import Bot
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(
            chat_id=CHAT_ID,
            text=build_review_text(),
            reply_markup=build_review_keyboard(),
            parse_mode="HTML",
        )
        print("[Telegram] Review prompt sent")

    def _run_in_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_send())
        loop.close()

    t = threading.Thread(target=_run_in_thread)
    t.start()
    t.join()


# ─── Persistent bot (handles article selection + draft review in one process) ──

def start_persistent_bot():

    # ── helpers ──────────────────────────────────────────────────────────────

    def _run_blocking_in_thread(fn, *args, **kwargs):
        """Run a blocking call in the executor so the asyncio loop isn't stalled."""
        loop = asyncio.get_running_loop()
        return loop.run_in_executor(_executor, lambda: fn(*args, **kwargs))

    async def _resume_workflow(thread_id, resume_value):
        """Resume the master workflow with a Command. Runs in executor because
        invoke() is synchronous and may hit another interrupt()."""
        config = {"configurable": {"thread_id": thread_id}}

        def _invoke():
            from workflow import master_workflow
            try:
                master_workflow.invoke(Command(resume=resume_value), config=config)
            except GraphInterrupt:
                pass  # expected when the workflow hits the next interrupt()

        await _run_blocking_in_thread(_invoke)

    # ── article-selection button handler ─────────────────────────────────────

    async def _handle_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, session: dict):
        query = update.callback_query
        mode = session["mode"]
        thread_id = session["thread_id"]

        r = _redis()
        articles_raw = r.get(f"buzzbot:{mode}_articles")
        articles = json.loads(articles_raw) if articles_raw else []

        def build_keyboard(selected_set):
            buttons = []
            for i, article in enumerate(articles):
                title = article.get("title")
                final_title = title[:title.rfind("-")].strip() if title and "-" in title else title
                preview = (final_title[:28].rstrip() + "...") if len(final_title) > 31 else final_title
                label = f"{i + 1}. {preview}  ✅" if i in selected_set else f"{i + 1}. {preview}"
                buttons.append([InlineKeyboardButton(label, callback_data=f"toggle:{i}")])
            buttons.append([
                InlineKeyboardButton("✅ Select All", callback_data="select_all"),
                InlineKeyboardButton("🧹 Clear", callback_data="clear_all"),
            ])
            buttons.append([InlineKeyboardButton("🚀 Save & Finish", callback_data="done")])
            return InlineKeyboardMarkup(buttons)

        selected = context.user_data.get("selected", set())

        if query.data == "done":
            chosen = [articles[i] for i in sorted(selected)]
            context.user_data["selected"] = set()

            await query.edit_message_text(f"✅ Saved {len(chosen)} articles. Resuming workflow...")

            # Resume the workflow — this will run through make_linkedin_post
            # and then hit the next interrupt (weekly_wait_for_review).
            # We no longer call stop_running() — the persistent bot stays alive
            # to handle the review step too.
            await _resume_workflow(thread_id, chosen)
            return

        if query.data == "select_all":
            selected.update(range(len(articles)))
        elif query.data == "clear_all":
            selected.clear()
        elif query.data.startswith("toggle:"):
            idx = int(query.data.split(":")[1])
            if idx in selected:
                selected.remove(idx)
            else:
                selected.add(idx)

        context.user_data["selected"] = selected
        await query.edit_message_reply_markup(reply_markup=build_keyboard(selected))

    # ── review button handlers ────────────────────────────────────────────────

    async def _handle_review_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the three review buttons: Post, Reprompt LLM, Edit Post."""
        query = update.callback_query
        await query.answer()

        session = _get_active_session()
        if not session:
            await query.edit_message_text("No active review session found.")
            return

        thread_id = session["thread_id"]

        if query.data == "post":
            await query.edit_message_text("✅ Post approved! Publishing to LinkedIn...")
            _clear_active_session()
            await _resume_workflow(thread_id, {"approve_status": "post"})

        elif query.data == "prompt_llm":
            context.user_data["review_state"] = "waiting_for_prompt"
            context.user_data["review_thread_id"] = thread_id
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                "✍️ Please type your prompt / instructions for the LLM and send it as a message:"
            )

        elif query.data == "edit_post":
            context.user_data["review_state"] = "waiting_for_edit"
            context.user_data["review_thread_id"] = thread_id
            await query.edit_message_reply_markup(reply_markup=None)
            r = _redis()
            draft = (r.get("buzzbot:weekly_review_draft") or b"").decode()
            await query.message.reply_text(
                "✏️ <b>Here is your draft post.</b> Long-press to copy it, make your edits, and send it back as a message:",
                parse_mode="HTML",
            )
            await query.message.reply_text(draft)

    async def _handle_review_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle confirm / re-edit button presses during the edit flow."""
        query = update.callback_query
        await query.answer()

        thread_id = context.user_data.get("review_thread_id")
        review_state = context.user_data.get("review_state")

        if not thread_id or review_state != "waiting_for_edit_confirm":
            await query.edit_message_text("This review session has expired. No action taken.")
            return

        if query.data == "confirm_edit":
            final_post = context.user_data.get("pending_edited_post", "")
            context.user_data.pop("review_state", None)
            context.user_data.pop("review_thread_id", None)
            context.user_data.pop("pending_edited_post", None)

            await query.edit_message_text(
                f"✅ <b>Saved! Here is your final post:</b>\n\n{html.escape(final_post)}",
                parse_mode="HTML",
            )
            _clear_active_session()
            await _resume_workflow(thread_id, {
                "approve_status": "edit_post",
                "edited_response": final_post,
            })

        elif query.data == "redo_edit":
            context.user_data["review_state"] = "waiting_for_edit"
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text(
                "✍️ No problem! Please send back the updated version of the post:"
            )

    async def _handle_review_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle user text messages during the review flow (prompt input or edit input)."""
        state = context.user_data.get("review_state")
        if not state:
            return  # not in a review conversation

        thread_id = context.user_data.get("review_thread_id")
        if not thread_id:
            return  # stale session, nothing to do

        if state == "waiting_for_prompt":
            user_prompt = update.message.text.strip()

            await update.message.reply_text(
                f"⚙️ Got it! Sending your prompt to the LLM...\n\n"
                f"<i>Prompt: {html.escape(user_prompt)}</i>",
                parse_mode="HTML",
            )

            r = _redis()
            draft = (r.get("buzzbot:weekly_review_draft") or b"").decode()

            # Run the blocking LLM call in a thread so we don't stall the event loop
            edited = await _run_blocking_in_thread(
                edit_draft_post_w_prompt, instruction=user_prompt, draft_post=draft
            )

            await update.message.reply_text(
                f"✅ <b>Edited Post:</b>\n\n{html.escape(edited)}",
                parse_mode="HTML",
            )

            context.user_data.pop("review_state", None)
            context.user_data.pop("review_thread_id", None)
            _clear_active_session()
            await _resume_workflow(thread_id, {
                "approve_status": "prompt_llm",
                "user_prompt": user_prompt,
                "edited_response": edited,
            })

        elif state == "waiting_for_edit":
            edited_text = update.message.text.strip()
            context.user_data["pending_edited_post"] = edited_text
            context.user_data["review_state"] = "waiting_for_edit_confirm"

            confirm_keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("✅ Confirm",   callback_data="confirm_edit"),
                    InlineKeyboardButton("🔁 Re-edit",  callback_data="redo_edit"),
                ]
            ])

            await update.message.reply_text(
                f"📋 <b>Here is your edited post</b>\n\n{html.escape(edited_text)}",
                reply_markup=confirm_keyboard,
                parse_mode="HTML",
            )

    # ── main dispatcher ──────────────────────────────────────────────────────

    async def handle_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        session = _get_active_session()
        if not session:
            await query.edit_message_text("No active session found.")
            return

        mode = session["mode"]

        if mode == "weekly_review":
            await _handle_review_button(update, context)
            return

        if mode in ("daily", "weekly"):
            await _handle_selection(update, context, session)
            return

    # ── build app ────────────────────────────────────────────────────────────

    app = Application.builder().token(BOT_TOKEN).build()
    # Specific handlers first so they take priority over the generic dispatcher
    app.add_handler(CallbackQueryHandler(_handle_review_confirm, pattern="^(confirm_edit|redo_edit)$"))
    app.add_handler(CallbackQueryHandler(handle_button))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _handle_review_message))

    print("[PersistentBot] Polling for interactions...")
    app.run_polling()