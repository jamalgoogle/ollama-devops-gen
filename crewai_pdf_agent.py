import sys
from crewai import Agent, Task, Crew, Process, LLM   # pip install crewai
from crewai.tools import tool                        # turns a function into a tool
from rag_pdf_qa import build_index, search           # our RAG code from above

pdf_path = sys.argv[1]
chunks, vectors = build_index(pdf_path)              # read + embed the PDF once

# The LLM that all agents will use (local, through Ollama)
llm = LLM(model="ollama/llama3.1:8b", base_url="http://localhost:11434")

@tool("Search internal documentation")               # the name the agent sees
def search_docs(question: str) -> str:
    """Search the internal PDF and return the most useful parts for the question."""
    return "\n---\n".join(search(question, chunks, vectors))   # reuse our search

# AGENT 1: finds the facts
researcher = Agent(
    role="Internal Docs Researcher",
    goal="Find the exact facts in the company documentation",
    backstory="You know the company handbook very well and never guess.",
    tools=[search_docs], llm=llm, verbose=True)

# AGENT 2: writes the final answer
support = Agent(
    role="Support Engineer",
    goal="Give a short, clear answer in simple English",
    backstory="You help new engineers. You only use facts from the researcher.",
    llm=llm, verbose=True)

# TASKS: what each agent must do ({question} is filled by kickoff)
find = Task(
    description="Search the docs and collect the facts for this question: {question}",
    expected_output="A list of facts from the documentation. Say 'not found' if missing.",
    agent=researcher)
write = Task(
    description="Write the final answer for: {question}. Use only the facts from the researcher.",
    expected_output="A short answer (max 5 lines) and the section name if known.",
    agent=support, context=[find])                   # context = use the result of 'find'

crew = Crew(agents=[researcher, support], tasks=[find, write],
            process=Process.sequential, verbose=True)   # tasks run one after another

if __name__ == "__main__":
    result = crew.kickoff(inputs={"question": input("Question> ")})
    print("\nFINAL ANSWER:\n", result)
