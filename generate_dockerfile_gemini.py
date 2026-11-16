import google.generativeai as genai   # Google's Python library for Gemini
import os                             # to read environment variables

# FIX: never write the key in the code. Read it from the environment instead.
# Linux/Mac: export GOOGLE_API_KEY="your-key"    Windows: setx GOOGLE_API_KEY "your-key"
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:                                  # stop early with a clear message
    raise SystemExit("Please set the GOOGLE_API_KEY environment variable first.")

genai.configure(api_key=API_KEY)                 # give the key to the library

# The repo used 'gemini-1.5-pro'. Old models can be shut down by Google,
# so check the current model names in Google AI Studio and change this line.
MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-1.5-pro")
model = genai.GenerativeModel(MODEL_NAME)        # create the model object

PROMPT = """
Generate an ideal Dockerfile for {language} with best practices. Just share the dockerfile without any explanation between two lines to make copying dockerfile easy.
Include:
- Base image
- Installing dependencies
- Setting working directory
- Adding source code
- Running the application
"""

def generate_dockerfile(language):
    # Fill {language} in the prompt, send it to Gemini, and get the answer.
    response = model.generate_content(PROMPT.format(language=language))
    return response.text                         # the answer as plain text

if __name__ == "__main__":
    language = input("Enter the programming language: ")   # ask the user
    dockerfile = generate_dockerfile(language)              # call the AI
    print("\nGenerated Dockerfile:\n")
    print(dockerfile)
