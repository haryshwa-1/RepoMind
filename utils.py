import os
import re
import json
import uuid
import tempfile
import time
from git import Repo

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_groq import ChatGroq
from langchain_classic.chains import RetrievalQA
from langchain_core.prompts import PromptTemplate
from langchain_core.messages import HumanMessage, SystemMessage
import subprocess


def clone_repo(url):
    path = tempfile.mkdtemp()
    Repo.clone_from(url, path)
    return path

def load_documents(path):
    docs = []
    allowed_ext = (
        ".py", ".js", ".ts", ".jsx", ".tsx",
        ".html", ".css", ".scss", ".md",
        ".json", ".java", ".cpp", ".c", ".go",
        ".rs", ".php", ".rb", ".sh", ".yml", ".yaml"
    )
    ignored_dirs = {
        ".git", "node_modules", "venv", "__pycache__",
        ".next", "dist", "build", ".idea", ".vscode"
    }

    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]
        for file in files:
            if file.endswith(allowed_ext):
                file_path = os.path.join(root, file)
                try:
                    loader = TextLoader(file_path, encoding="utf-8")
                    docs.extend(loader.load())
                except:
                    pass
    return docs

def split_docs(docs):
    chunks = []
    default_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
    ext_to_lang = {
        ".py": Language.PYTHON, ".js": Language.JS, ".ts": Language.TS,
        ".jsx": Language.JS, ".tsx": Language.TS, ".html": Language.HTML,
        ".md": Language.MARKDOWN, ".java": Language.JAVA, ".cpp": Language.CPP,
        ".c": Language.CPP, ".go": Language.GO, ".rs": Language.RUST,
        ".php": Language.PHP, ".rb": Language.RUBY,
    }

    for doc in docs:
        source = doc.metadata.get("source", "")
        ext = os.path.splitext(source)[1].lower()
        if ext in ext_to_lang:
            splitter = RecursiveCharacterTextSplitter.from_language(
                language=ext_to_lang[ext], chunk_size=1000, chunk_overlap=100
            )
            chunks.extend(splitter.split_documents([doc]))
        else:
            chunks.extend(default_splitter.split_documents([doc]))
            
    return chunks

def create_vectorstore(chunks):
    emb = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")
    persist_dir = os.path.join(tempfile.gettempdir(), f"chromadb_{uuid.uuid4().hex}")
    vectordb = Chroma.from_documents(documents=chunks, embedding=emb, persist_directory=persist_dir)
    return vectordb, persist_dir

def create_qa_chain(vectordb, groq_key, file_tree, security_mode=False):
    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        api_key=groq_key,
        temperature=0.0 if security_mode else 0.2
    )

    if security_mode:
        prompt_template = f"""
You are an automated Static Application Security Testing (SAST) framework and a strict Cybersecurity Engineer.
Your ONLY objective is to analyze the provided code context and detect OWASP Top 10 vulnerabilities.

Here is the overall architecture of the repository:
{file_tree}

CRITICAL RULES:
1. You must ONLY output identified vulnerabilities that are EXPLICITLY FOUND in the provided Context.
2. DO NOT hallucinate. DO NOT assume vulnerabilities exist in files you cannot see. If a vulnerability is "not shown in the snippet", you MUST NOT report it. 
3. No conversational filler, greetings, or conclusions.
4. If no vulnerabilities are clearly found in the specific context provided, output exactly: "No obvious OWASP vulnerabilities detected in the current context."
5. If vulnerabilities ARE found, you MUST use the exact format below. You MUST include double line breaks between each field so it renders correctly in Markdown:

**Vulnerability Name:** [Name of the vulnerability]

**CWE ID:** [e.g., CWE-89]

**Severity:** [Critical, High, Medium, or Low]

**Line Context:** [Filename and exact code snippet]

**Fix:** [A precise, 1-sentence instruction to remediate the issue]

---

Do not deviate from this format. 

Question: {{question}}
Context: {{context}}

Answer:
"""
    else:
        prompt_template = f"""
You are RepoMind, an expert software engineer and repository analyst.
Answer ONLY using the repository context provided below.
If the answer is not clearly available in the context, say: "I could not confidently find that in the repository."

Here is the overall architecture of the repository:
{file_tree}

Rules:
- Be specific and practical.
- Mention filenames when relevant.
- Do NOT guess or hallucinate.
- Keep answers clear and structured.

Question: {{question}}
Context: {{context}}

Answer:
"""

    PROMPT = PromptTemplate(template=prompt_template, input_variables=["context", "question"])

    return RetrievalQA.from_chain_type(
        llm=llm,
        retriever=vectordb.as_retriever(search_kwargs={"k": 10}),
        chain_type="stuff",
        return_source_documents=True,
        chain_type_kwargs={"prompt": PROMPT}
    )

def get_file_tree(path):
    tree = ""
    ignored_dirs = {".git", "node_modules", "venv", "__pycache__", ".next", "dist", "build", ".idea", ".vscode"}
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]
        level = root.replace(path, "").count(os.sep)
        indent = "  " * level
        folder_name = os.path.basename(root) if os.path.basename(root) else "repo"
        tree += f"{indent}{folder_name}/\n"
        for f in files:
            tree += f"{indent}  {f}\n"
    return tree

def detect_project_type(path):
    files = set()
    for root, _, filenames in os.walk(path):
        for f in filenames:
            files.add(f.lower())

    if "package.json" in files:
        if "vite.config.js" in files or "vite.config.ts" in files: return "Vite / JavaScript or React Project"
        if "next.config.js" in files: return "Next.js Project"
        return "JavaScript / Node.js Project"
    if "requirements.txt" in files or "app.py" in files: return "Python Project"
    if "pom.xml" in files: return "Java / Maven Project"
    if "cargo.toml" in files: return "Rust Project"
    if "go.mod" in files: return "Go Project"
    return "Unknown / Mixed Tech Project"

def extract_dependencies(path):
    deps = []
    
    package_json = os.path.join(path, "package.json")
    if os.path.exists(package_json):
        try:
            with open(package_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                for section in ["dependencies", "devDependencies"]:
                    if section in data: deps.extend(list(data[section].keys()))
        except: pass

    requirements = os.path.join(path, "requirements.txt")
    if os.path.exists(requirements):
        try:
            with open(requirements, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"): deps.append(line)
        except: pass

    pom = os.path.join(path, "pom.xml")
    if os.path.exists(pom):
        try:
            with open(pom, "r", encoding="utf-8") as f:
                matches = re.findall(r"<artifactId>(.*?)</artifactId>", f.read())
                deps.extend(matches)
        except: pass

    return sorted(list(set(deps)))

# -------------------------
# Deterministic Scanner (Phase 1)
# -------------------------
def run_semgrep(repo_path):
    """
    Runs Semgrep CLI. 
    Forces local rules and completely disables telemetry to prevent opentelemetry crashes.
    """
    try:
        command = [
            "semgrep", "scan", 
            "--config=p/default", 
            "--json", 
            "--quiet", 
            repo_path
        ]
        
        # Clone the current OS environment and inject the kill-switch for metrics
        custom_env = os.environ.copy()
        custom_env["SEMGREP_SEND_METRICS"] = "off"
        custom_env["SEMGREP_ENABLE_METRICS"] = "off"
        
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
            env=custom_env # Pass the modified environment
        )
        
        if result.stdout:
            return json.loads(result.stdout)
        else:
            return {"error": "Semgrep executed but returned no output.", "stderr": result.stderr}
            
    except Exception as e:
        return {"error": f"An unexpected execution error occurred: {str(e)}"}

# -------------------------
# Segment 2: Parser & Snippet Extractor
# -------------------------
def get_code_snippet(file_path, line_number, context_lines=5):
    """Reads the file and grabs the vulnerable line plus surrounding context."""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        start_idx = max(0, line_number - 1 - context_lines)
        end_idx = min(len(lines), line_number + context_lines)
        
        snippet = "".join(lines[start_idx:end_idx])
        return snippet
    except Exception as e:
        return f"Could not extract snippet: {e}"

def parse_semgrep_output(raw_json):
    """Strips metadata, fetches snippets, AND catches errors."""
    
    # NEW: Catch the error so it doesn't fail silently!
    if "error" in raw_json:
        return [{
            "vulnerability": "Execution Error", 
            "message": f"Semgrep failed: {raw_json.get('error')} | STDERR: {raw_json.get('stderr', '')}", 
            "file": "System", 
            "cwe": "N/A"
        }]

    parsed_alerts = []
    results = raw_json.get("results", [])
    
    for r in results:
        file_path = r.get("path", "")
        line_num = r.get("start", {}).get("line", 0)
        
        alert = {
            "file": os.path.basename(file_path),
            "full_path": file_path,
            "line": line_num,
            "vulnerability": r.get("check_id", ""),
            "message": r.get("extra", {}).get("message", ""),
            "cwe": r.get("extra", {}).get("metadata", {}).get("cwe", "Unknown"),
            "severity": r.get("extra", {}).get("severity", "WARNING"),
            "code_snippet": get_code_snippet(file_path, line_num)
        }
        parsed_alerts.append(alert)
        
    return parsed_alerts

# -------------------------
# Segment 2: The Scout Agent (Rate Limited)
# -------------------------
def run_scout_agent(parsed_alerts, groq_key):
    """Passes the cleaned alerts and code snippets to the LLM for Initial Triage."""
    if not parsed_alerts:
        return "No vulnerabilities detected by the deterministic scanner."
        
    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        api_key=groq_key,
        temperature=0.1
    )
    
    system_prompt = """
You are the "Logic Scout" for an advanced SAST framework.
A deterministic scanner (Semgrep) has flagged the following code snippets for potential vulnerabilities.

YOUR JOB:
1. Read the code snippet and the scanner's message.
2. Filter out obvious false positives (e.g., if it flags a missing security header, but it's clearly a local test file).
3. For legitimate findings, rewrite the dense scanner message into a clear, single paragraph explaining the *logical* risk to the application.

OUTPUT FORMAT:
Output your analysis in a clean Markdown format. 
Use ### for the Vulnerability Name. 
Do not output anything else.
"""
    
    all_responses = []
    
    # RATE LIMITING LOGIC
    # Groq allows 6,000 Tokens Per Minute. We send 5 alerts per batch, then sleep for 60 seconds.
    CHUNK_SIZE = 5
    SLEEP_TIME = 60
    
    for i in range(0, len(parsed_alerts), CHUNK_SIZE):
        chunk = parsed_alerts[i:i + CHUNK_SIZE]
        alerts_text = json.dumps(chunk, indent=2)
        
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=f"Analyze these deterministic findings:\n\n{alerts_text}")
        ]
        
        try:
            response = llm.invoke(messages)
            all_responses.append(response.content)
        except Exception as e:
            all_responses.append(f"### Error analyzing chunk\n{str(e)}")
            
        # If there are still more chunks left to process, sleep to reset the TPM limit
        if i + CHUNK_SIZE < len(parsed_alerts):
            time.sleep(SLEEP_TIME)
            
    return "\n\n".join(all_responses)

# -------------------------
# Segment 3: The Verifier Agent (Rate Limited)
# -------------------------
def run_verifier_agent(parsed_alerts, vectordb, groq_key):
    """
    Phase 3: The Context Verifier. 
    Uses the Vector DB to search for mitigating controls across the entire repo.
    """
    if not parsed_alerts or not vectordb:
        return "Verification skipped: No alerts or vector database available."

    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        api_key=groq_key,
        temperature=0.0 # Zero temperature for strict verification
    )

    verified_results = []
    retriever = vectordb.as_retriever(search_kwargs={"k": 5})

    # RATE LIMITING LOGIC
    # RAG context is heavy (Prompt + 5 DB Chunks). We can only safely process 3 alerts per minute.
    CHUNK_SIZE = 3
    SLEEP_TIME = 60

    for i in range(0, len(parsed_alerts), CHUNK_SIZE):
        chunk = parsed_alerts[i:i + CHUNK_SIZE]
        
        # Process the small chunk of 3 alerts
        for alert in chunk:
            vuln_name = alert.get('vulnerability', 'vulnerability')
            file_name = alert.get('file', 'code')
            cwe = alert.get('cwe', '')

            search_query = f"security configuration middleware defenses {vuln_name} {cwe} in {file_name}"
            docs = retriever.invoke(search_query)

            context_texts = [f"File: {d.metadata.get('source', 'Unknown')}\n{d.page_content}" for d in docs]
            combined_context = "\n---\n".join(context_texts)

            system_prompt = f"""
You are the "Verifier Agent" for a Multi-Pass SAST framework.
A deterministic scanner flagged a potential vulnerability, but it might be a false positive if mitigating controls exist elsewhere in the repository.

VULNERABILITY TO VERIFY:
File: {file_name}
Issue: {alert.get('message', '')}
Snippet:
{alert.get('code_snippet', '')}

GLOBAL CONTEXT (Retrieved via RAG):
{combined_context}

YOUR JOB:
1. Analyze the GLOBAL CONTEXT to see if there is a mitigating control (e.g., a global sanitizer, a security middleware applied elsewhere, HTTPS enforced at a proxy level).
2. Make a final judgment: VALIDATED (True Vulnerability) or MITIGATED (False Positive).
3. Explain your reasoning briefly.

OUTPUT FORMAT (Use exactly this Markdown):
### 🛡️ Verification: {vuln_name.split('.')[-1]}
**Status:** [VALIDATED or MITIGATED]
<br>**Reasoning:** [1-2 sentences explaining why based on the global context]
---
"""
            messages = [SystemMessage(content=system_prompt)]
            
            try:
                response = llm.invoke(messages)
                verified_results.append(response.content)
            except Exception as e:
                verified_results.append(f"### 🛡️ Verification: {vuln_name}\n**Status:** ERROR\n<br>**Reasoning:** API Rate Limit or Execution Error - {str(e)}\n---")
        
        # If there are still more chunks left, sleep to avoid hitting the RPM/TPM limit
        if i + CHUNK_SIZE < len(parsed_alerts):
            time.sleep(SLEEP_TIME)

    return "\n".join(verified_results)
