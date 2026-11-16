import sys
import requests                      # download web pages
from bs4 import BeautifulSoup        # pip install beautifulsoup4 (remove HTML tags)
import ollama

MODEL = "llama3.1:8b"

def ask(system, user):               # one helper = one "agent call"
    r = ollama.chat(model=MODEL, messages=[
        {"role": "system", "content": system},
        {"role": "user", "content": user}])
    return r["message"]["content"]

def read_url(url, limit=6000):       # TOOL: read a web page as plain text
    html = requests.get(url, timeout=20, headers={"User-Agent": "study-agent"}).text
    text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
    return text[:limit]              # cut it: models can only read a limited size

def research_and_write(topic, urls):
    # AGENT 1: Researcher. Reads the pages and writes short notes.
    notes = []
    for url in urls:
        page = read_url(url)
        notes.append(ask(
            "You are a careful researcher. Use ONLY the text given. Write 5 short bullet points.",
            f"Topic: {topic}\nSource: {url}\nText:\n{page}"))
    all_notes = "\n\n".join(notes)

    # AGENT 2: Writer. Turns the notes into a blog article.
    blog = ask(
        "You are a technical blogger. Write in simple English with a title, an intro, "
        "3 short sections with headings, and a conclusion. Use ONLY the notes.",
        f"Topic: {topic}\nNotes:\n{all_notes}")

    # AGENT 3: Reviewer. Checks the article against the notes (reduces hallucinations).
    review = ask(
        "You are an editor. List any sentence that is NOT supported by the notes. "
        "If all is fine, write: OK.",
        f"Notes:\n{all_notes}\n\nArticle:\n{blog}")
    return blog, review

if __name__ == "__main__":
    topic = sys.argv[1]              # python research_agent.py "What is AIOps?" url1 url2
    blog, review = research_and_write(topic, sys.argv[2:])
    print(blog)
    print("\n--- Reviewer says ---\n" + review)
