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
    final_prompt_string = langchain_prompt.format(
        articles=json.dumps(state['final_news'], indent=2)
    )

    response = llm.invoke(final_prompt_string, config={"callbacks": [langfuse_handler]})

    return response.content