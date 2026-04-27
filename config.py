import os
from dotenv import load_dotenv

load_dotenv()

# LangSmith tracing — enabled only when LANGSMITH_API_KEY is set in .env
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY", "")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "fraud-agent")

if LANGSMITH_API_KEY:
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"]    = LANGSMITH_API_KEY
    os.environ["LANGCHAIN_PROJECT"]    = LANGSMITH_PROJECT
else:
    os.environ["LANGCHAIN_TRACING_V2"] = "false"
    os.environ.pop("LANGCHAIN_API_KEY", None)
    os.environ.pop("LANGSMITH_API_KEY", None)

GEMINI_API_KEY         = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY           = os.getenv("GROQ_API_KEY", "")
OPENAI_API_KEY         = os.getenv("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY      = os.getenv("ANTHROPIC_API_KEY", "")
TAVILY_API_KEY         = os.getenv("TAVILY_API_KEY", "")
SERPER_API_KEY         = os.getenv("SERPER_API_KEY", "")
OPENSANCTIONS_API_KEY  = os.getenv("OPENSANCTIONS_API_KEY", "")

# Database (optional — app works without these, falls back to local JSON)
MONGODB_URI  = os.getenv("MONGODB_URI", "")
NEO4J_URI      = os.getenv("NEO4J_URI", "")
NEO4J_USER     = os.getenv("NEO4J_USER", os.getenv("NEO4J_USERNAME", "neo4j"))
NEO4J_PASS     = os.getenv("NEO4J_PASS", os.getenv("NEO4J_PASSWORD", ""))
NEO4J_DATABASE = os.getenv("NEO4J_DATABASE", "neo4j")

PRIMARY_MODEL   = "gemini-3.1-flash-lite-preview"
EVALUATOR_MODEL = "gemini-3.1-flash-lite-preview"
FALLBACK_MODEL  = "meta-llama/llama-4-scout-17b-16e-instruct"

MAX_ITERATIONS   = 8
STAGNATION_LIMIT = 3   # stop if last N iters found 0 new entities AND no high-pri left
MIN_CONFIDENCE   = 0.60
