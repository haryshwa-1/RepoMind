# 🧠 RepoMind

**Intelligent code analysis and repository exploration.**

RepoMind is a high-performance tool designed for developers to "talk" to any GitHub repository. By combining Vector Embeddings with the speed of the Groq Llama 3.1 inference engine, RepoMind allows you to clone, analyze, and query complex codebases using natural language.

---

## 🚀 Core Features

* **Instant Repository Analysis:** Simply paste a GitHub URL to clone and index the entire codebase in seconds.
* **Language-Aware Chunking:** Uses specialized logic to split code by functions and classes (Python, JS, TS, C++, Go, etc.), ensuring the AI never loses context.
* **Deep Technical QA:** Ask questions about architecture, find entry points, or explain complex logic across multiple files.
* **Automated Project Summary:** Get an AI-generated technical overview of any project’s purpose and architecture.
* **Visual File Tree:** Browse the repository structure directly within the dashboard.
* **Auto-README Builder:** Generate a professional, high-quality `README.md` for any analyzed project with one click.

---

## 🛠️ The Tech Stack

* **Frontend:** [Streamlit](https://streamlit.io/)
* **Orchestration:** [LangChain](https://www.langchain.com/)
* **Inference Engine:** [Groq Cloud](https://groq.com/) (Llama 3.1 8B)
* **Vector Database:** [ChromaDB](https://www.trychroma.com/)
* **Embeddings:** [HuggingFace](https://huggingface.co/) (`all-MiniLM-L6-v2`)
* **Backend Logic:** Python & GitPython

---

## 📦 Installation & Local Setup

If you want to run RepoMind on your local machine:

### 1. Clone and run the Project
```bash
git clone [https://github.com/haryshwa-1/RepoMind.git](https://github.com/haryshwa-1/RepoMind.git)
cd RepoMind
python -m venv venv
source venv/bin/activate  # On Windows use: venv\Scripts\activate
pip install -r requirements.txt
#Open app.py and replace the GROQ_API_KEY placeholder with your actual key from the Groq Console.
streamlit run app.py
