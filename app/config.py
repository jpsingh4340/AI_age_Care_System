import os

# Where Ollama is running. It starts by itself on your laptop after you install it.
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

# The small language model (SLM) that reads the note and writes the summary.
# Change it later without touching any other file, for example:
#   $env:CHAT_MODEL = "llama3.2:3b"
CHAT_MODEL = os.getenv("CHAT_MODEL", "llama3.2:3b")

# The small model that turns text into numbers so we can search by meaning (RAG).
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
