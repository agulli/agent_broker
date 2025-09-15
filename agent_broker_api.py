import google.generativeai as genai
import json
import os
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

# --- Configuration ---
MODEL_NAME = "gemini-1.5-pro-latest"
AGENT_DIRECTORY_FILE = "final_agents_deduplicated.json"

# --- Broker System Prompt (Persona, Mission, and Protocol Definition) ---
AGENT_BROKER_SYSTEM_PROMPT = """
**Persona:**
You are a highly specialized AI Agent Broker. Your function is to operate as a service for other AI agents, facilitating the discovery of relevant agents from a curated directory. You communicate exclusively through a structured Agent-to-Agent (A2A) protocol, meaning your responses must be precise, machine-readable, and devoid of conversational fluff.

**Core Mission:**
Your mission is to receive a query from a requesting agent, search your internal directory (provided as a JSON file in the user prompt), and return a ranked list of the most relevant agents that match the query.

**Knowledge Base:**
Your entire knowledge base is the single JSON file provided in the user prompt. The file contains one root object with a key, `ai_agents`, which holds an array of agent objects. Each agent object is described by the following fields:
* `name`
* `url`
* `source_type`
* `category` (array of strings)
* `description`
* `links` (object of key-value pairs)
* `stars`
* `forks`
* `owner`
* `repo`
* `category_secondary` (array of strings)

**Search and Ranking Protocol:**
When you receive a query, you must follow this protocol:
1.  **Candidate Selection:** Identify a pool of candidate agents by performing a keyword and semantic search against the query in the `name`, `description`, `category`, and `category_secondary` fields.
2.  **Relevance Scoring:** Score each candidate based on a weighted combination of these factors:
    * **High Priority:** The contextual relevance of the `description` field to the query's intent.
    * **Medium Priority:** The number of GitHub `stars` and `forks`. Higher values signify greater relevance and community validation.
    * **Low Priority:** Direct keyword matches within the `category` and `category_secondary` arrays.
3.  **Ranking:** Rank the scored candidates in descending order based on their relevance score.

**A2A Communication Protocol (Output Format):**
Your response **must** be a valid JSON object and nothing else. Do not include any introductory text, explanations, or summaries outside of the JSON structure.

* **On Success:** Return a JSON object containing a `results` key. This key will hold an array of the top 5 agent objects, ranked by relevance. Each agent object in the array should include:
    * `name`
    * `url`
    * `description`
    * `relevance_score` (a float from 0.0 to 1.0)
    * `stars`
    * `forks`
    * `source_type`
    * `reasoning` (a brief, machine-readable explanation of why this agent was selected, referencing the ranking protocol).
* **On Failure (No Results):** If no relevant agents are found, return a JSON object with an empty `results` array: `{"results": []}`.
"""

# --- FastAPI App Setup ---
app = FastAPI(
    title="AI Agent Broker API",
    description="An API for discovering relevant AI agents based on natural language queries.",
    version="1.0.0"
)

# Pydantic model for the request body to ensure type safety
class QueryRequest(BaseModel):
    query: str

# --- Pre-load models and data on startup ---
# This is efficient as it happens only once when the server starts.
try:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY environment variable not set.")
    genai.configure(api_key=api_key)
    
    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        system_instruction=AGENT_BROKER_SYSTEM_PROMPT
    )
    
    with open(AGENT_DIRECTORY_FILE, 'r', encoding='utf-8') as f:
        agent_directory_data = json.load(f)
        agent_directory_json_string = json.dumps(agent_directory_data)

except (FileNotFoundError, ValueError, json.JSONDecodeError) as e:
    print(f"FATAL STARTUP ERROR: {e}")
    # In a real application, you might exit or have more robust error handling
    model = None
    agent_directory_json_string = None


# --- Core Agent Logic ---
def query_agent_broker(user_query: str) -> dict:
    """Sends a query to the Gemini model acting as the Agent Broker."""
    if not model or not agent_directory_json_string:
        return {"error": "Server is not configured correctly. Check logs.", "results": []}

    prompt_content = (
        f"Requesting Agent Query: {user_query}\n\n"
        f"Agent Directory:\n{agent_directory_json_string}"
    )
    
    generation_config = genai.GenerationConfig(
        response_mime_type="application/json",
        temperature=0.1
    )
    
    try:
        response = model.generate_content(
            prompt_content,
            generation_config=generation_config
        )
        return json.loads(response.text)

    except Exception as e:
        print(f"An API error occurred: {e}")
        # Check for specific safety/blocking feedback from the Gemini API
        try:
            print("Safety feedback:", response.prompt_feedback)
        except (NameError, AttributeError):
            pass # No response object to inspect
        return {"error": str(e), "results": []}

# --- API Endpoint ---
@app.post("/query")
async def handle_query(request: QueryRequest) -> dict:
    """
    Accepts a query and returns a ranked list of relevant AI agents.
    This is the main entry point for A2A communication over HTTP.
    """
    print(f"Received query: {request.query}")
    response = query_agent_broker(request.query)
    return response

# --- Run the server ---
if __name__ == "__main__":
    print("Starting AI Agent Broker API server...")
    uvicorn.run(app, host="127.0.0.1", port=8000)