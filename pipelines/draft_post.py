from langchain_groq import ChatGroq
from pydantic import BaseModel
from tracking.langfuse_client import langfuse_handler 
from langfuse import Langfuse
import json

llm = ChatGroq(model="llama-3.3-70b-versatile")
langfuse = Langfuse()

def draft_post(state):
    prompt = langfuse.get_prompt("DraftPost/v1", version=1)

    langchain_prompt = prompt.get_langchain_prompt()
    articles_for_prompt = [
        {
            "title":   article.get("title", ""),
            "content": article.get("content", ""),
        }
        for article in state["final_news"]
    ]

    final_prompt_string = langchain_prompt.format(
        articals=json.dumps(articles_for_prompt, indent=2)
    )

    response = llm.invoke(final_prompt_string, config={"callbacks": [langfuse_handler]})

    return response.content