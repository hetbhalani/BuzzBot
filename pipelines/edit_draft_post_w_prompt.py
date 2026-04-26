from langchain_groq import ChatGroq
from tavily_search_tool import tavily_search
from langchain.agents import create_tool_calling_agent
from langchain.agents import AgentExecutor
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder


tools = [tavily_search]
llm = ChatGroq(model="llama-3.3-70b-versatile")

prompt_template = ChatPromptTemplate.from_messages(
    [
        ("system", "You are an expert LinkedIn ghostwriter and editor. Your job is to modify an existing LinkedIn post draft based on the user's instructions.\n\n"
                   "You have access to a web search tool. If the user's instructions require you to look up recent facts, news, or information you don't know, use the search tool.\n"
                   "If the instructions are simple edits (like making it shorter, changing the tone, or fixing grammar), just apply them directly without using the tool.\n\n"
                   "IMPORTANT: Your final output must ONLY contain the revised LinkedIn post. Do not include conversational text like 'Here is the edited post'."),
        ("user", "Draft Post:\n{draft_post}\n\nUser Instruction:\n{instruction}"),
        MessagesPlaceholder(variable_name="agent_scratchpad"),
    ]
)

agent = create_tool_calling_agent(llm, tools, prompt_template)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

def edit_draft_post_w_prompt(instruction: str, draft_post: str):
    result = agent_executor.invoke({
        "instruction": instruction,
        "draft_post": draft_post
    })

    print(result)
    
    return result["output"]