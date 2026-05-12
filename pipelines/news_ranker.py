from langchain_groq import ChatGroq
from tracking.langfuse_client import langfuse_handler 
from langfuse import Langfuse
import json

llm = ChatGroq(model="llama-3.3-70b-versatile")
langfuse = Langfuse()

def news_ranker(state):
    prompt = langfuse.get_prompt("RankNews/v1", version=3)

    langchain_prompt = prompt.get_langchain_prompt()
    final_prompt_string = langchain_prompt.format(
        articles=json.dumps(state['all_news'], indent=2)
    )

    response = llm.invoke(final_prompt_string, config={"callbacks": [langfuse_handler]})

    scores = json.loads(response.content)

    scored_news = sorted(
        zip(state['all_news'], scores),
        key=lambda x:x[1],
        reverse=True
    )

    top_10 = [a for a,b in scored_news[:10]]

    return top_10