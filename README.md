# AI Agent Broker

*A Prototype for the Future of Agent Discovery*

This project provides a simple yet powerful API server that acts as a directory service for AI agents. It's designed to be queried by other AI agents, enabling them to discover and select the best tools for a given task programmatically.

-----

## \#\# The Future of Search: From Human to Agent

Today, when developers look for a new tool or framework, they use search engines and browse websites designed for human eyes. Tomorrow, AI agents will perform these tasks autonomously. An AI software developer won't browse a website; it will query a service to find the best API for its needs.

**This project is an example of tomorrow's search.** It moves beyond human-centric UIs and provides a structured, machine-readable endpoint for **Agent-to-Agent (A2A) communication**.

-----

## \#\# What is this Project?

This repository contains a simple API server that functions as an **AI Agent Broker**. Its sole purpose is to receive a natural language query from another agent and respond with a ranked list of relevant agents from its directory (the `final_agents_deduplicated.json` file).

The communication is designed for A2A interaction:

  * **Input:** A simple JSON object containing a query.
  * **Output:** A structured JSON object containing a ranked list of results. No conversational text, no HTML—just pure, parsable data.

-----

## \#\# How It Works: The `relevance_score`

The core intelligence of the broker lies in its ability to rank potential agents. It does this by calculating a `relevance_score` for each candidate, which is a combination of several key factors:

  * **📈 Contextual Match:** The broker uses a powerful LLM (like Google Gemini) to analyze the query's semantic meaning and compares it against the `description`, `category`, and other text fields of each agent in its directory.
  * **⭐ Community Validation (`stars` & `forks`):** The broker uses GitHub **`stars`** and **`forks`** as a strong signal for an agent's quality, popularity, and relevance. A tool with high engagement is weighted more heavily, assuming it is more likely to be a robust solution.
  * **🤖 Combined Ranking:** These factors are synthesized into a single, normalized `relevance_score` between 0.0 and 1.0. This allows the requesting agent to easily identify the top candidate or set a minimum threshold for quality.

-----

## \#\# Getting Started

### 1\. Prerequisites

  * Python 3.8+
  * A Google Gemini API Key

### 2\. Installation & Setup

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/agulli/agent_broker.git
    cd agent_broker
    ```
2.  **Install dependencies:**
    ```bash
    pip install "fastapi[all]" google-generativeai
    ```
3.  **Set Environment Variable:**
    ```bash
    # For macOS / Linux
    export GOOGLE_API_KEY='your-api-key-here'

    # For Windows
    set GOOGLE_API_KEY=your-api-key-here
    ```
4.  **Add Data File:** Ensure the `final_agents_deduplicated.json` file is present in the project's root directory.

### 3\. Running the Server

Start the API server from your terminal:

```bash
python agent_broker_api.py
```

-----

## \#\# Example Interaction (A2A Communication)

Here is a live example of an agent (simulated by `curl`) querying the broker to find tools for software development.

### Server Output

This is what you'll see in the terminal where the server is running.

```
(agent-broker) antonio@tip-2 ai-agent-broker % python agent_broker_api.py
Starting AI Agent Broker API server...
INFO:     Started server process [95229]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
Received query: Find agents for automating software development
INFO:     127.0.0.1:59502 - "POST /query HTTP/1.1" 200 OK
```

### Client Request

Another agent would make the following HTTP request. You can simulate this from a new terminal window.

```bash
curl -X POST http://127.0.0.1:8000/query \
-H "Content-Type: application/json" \
-d '{"query": "Find agents for automating software development"}'
```

### Broker's JSON Response

The broker provides a clean, structured JSON response that another machine can immediately parse and use.

```json
{
  "results": [
    {
      "name": "OpenHands",
      "url": "https://github.com/All-Hands-AI/OpenHands",
      "description": "🙌 OpenHands: Code Less, Make More. (formerly OpenDevin), a platform for software development agents powered by AI",
      "relevance_score": 0.95,
      "stars": 62503,
      "forks": 7469,
      "source_type": "Open-source",
      "reasoning": "High relevance to software development automation due to explicit mention in description and high GitHub activity (stars and forks)."
    },
    {
      "name": "AgentDock",
      "url": "https://github.com/agentdock/agentdock",
      "description": "AgentDock provides the open-source foundation to build, manage, and deploy production-ready AI agents and workflows, frictionlessly.",
      "relevance_score": 0.85,
      "stars": 1497,
      "forks": 95,
      "source_type": "Open-source",
      "reasoning": "Relevant to software development automation through focus on building and deploying AI agents and workflows, with moderate GitHub activity."
    },
    {
      "name": "TaskWeaver",
      "url": "https://github.com/microsoft/TaskWeaver",
      "description": "A code-first agent framework for seamlessly planning and executing data analytics tasks.",
      "relevance_score": 0.8,
      "stars": 5869,
      "forks": 760,
      "source_type": "Open-source",
      "reasoning": "Related to software development through its code-first approach and focus on task planning and execution, with good GitHub activity."
    },
    {
      "name": "Codel",
      "url": "https://github.com/Codel-Social/Codel",
      "description": "Autonomous AI agent, inspired by Devin, designed for complex task execution with features like a secure sandboxed Docker environment, integrated browser for real-time web information, text editor, and PostgreSQL database for history tracking, highlighting its relevance to agentic AI through its ability to autonomously navigate and perform actions across terminal, browser, and editor interfaces",
      "relevance_score": 0.75,
      "stars": 512,
      "forks": 61,
      "source_type": "Open-source",
      "reasoning": "Mentions software development context (terminal, browser, editor) and complex task execution, with decent GitHub activity."
    },
    {
      "name": "RepoAgent",
      "url": "https://github.com/logspace-ai/repo-agent",
      "description": "An LLM-powered repository agent designed to assist developers and teams in generating documentation and understanding repositories quickly",
      "relevance_score": 0.7,
      "stars": 757,
      "forks": 65,
      "source_type": "Open-source",
      "reasoning": "Specifically designed for assisting developers with repository tasks, indicating relevance to software development, and moderate GitHub activity."
    }
  ]
}
```