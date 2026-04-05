import os
import re
import json
import uuid
import tempfile
from git import Repo

from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter, Language
from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_groq import ChatGroq
from langchain_classic.chains import RetrievalQA
from langchain_core.prompts import PromptTemplate


# -------------------------
# Clone Repo
# -------------------------
def clone_repo(url):
    path = tempfile.mkdtemp()
    Repo.clone_from(url, path)
    return path


# -------------------------
# Load Docs
# -------------------------
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


# -------------------------
# Split Docs (Language Aware)
# -------------------------
def split_docs(docs):
    chunks = []
    
    # Default fallback splitter for unknown extensions
    default_splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=100
    )

    # Map file extensions to LangChain's Language enum
    ext_to_lang = {
        ".py": Language.PYTHON,
        ".js": Language.JS,
        ".ts": Language.TS,
        ".jsx": Language.JS,
        ".tsx": Language.TS,
        ".html": Language.HTML,
        ".md": Language.MARKDOWN,
        ".java": Language.JAVA,
        ".cpp": Language.CPP,
        ".c": Language.CPP,
        ".go": Language.GO,
        ".rs": Language.RUST,
        ".php": Language.PHP,
        ".rb": Language.RUBY,
    }

    for doc in docs:
        source = doc.metadata.get("source", "")
        ext = os.path.splitext(source)[1].lower()
        
        if ext in ext_to_lang:
            # Use the language-specific logic to avoid breaking functions in half
            splitter = RecursiveCharacterTextSplitter.from_language(
                language=ext_to_lang[ext],
                chunk_size=1000,
                chunk_overlap=100
            )
            chunks.extend(splitter.split_documents([doc]))
        else:
            chunks.extend(default_splitter.split_documents([doc]))
            
    return chunks


# -------------------------
# Vector Store
# -------------------------
def create_vectorstore(chunks):
    emb = HuggingFaceEmbeddings(model_name="all-MiniLM-L6-v2")

    persist_dir = os.path.join(tempfile.gettempdir(), f"chromadb_{uuid.uuid4().hex}")

    vectordb = Chroma.from_documents(
        documents=chunks,
        embedding=emb,
        persist_directory=persist_dir
    )

    return vectordb, persist_dir


# -------------------------
# QA Chain
# -------------------------
def create_qa_chain(vectordb, groq_key, file_tree):
    llm = ChatGroq(
        model="llama-3.1-8b-instant",
        api_key=groq_key,
        temperature=0.2
    )

    # We inject the file_tree directly into the prompt so the AI always knows the architecture
    prompt_template = f"""
You are RepoMind, an expert software engineer and repository analyst.

Answer ONLY using the repository context provided below.
If the answer is not clearly available in the context, say:
"I could not confidently find that in the repository."

Here is the overall folder and file structure of the repository to help you understand the architecture:
{file_tree}

Rules:
- Be specific and practical.
- Mention filenames when relevant.
- Do NOT guess or hallucinate.
- Keep answers clear and structured.
- If asked about dependencies, infer only from actual files like package.json, requirements.txt, pom.xml, etc.

Question: {{question}}
Context: {{context}}

Answer:
"""

    PROMPT = PromptTemplate(
        template=prompt_template, input_variables=["context", "question"]
    )

    return RetrievalQA.from_chain_type(
        llm=llm,
        retriever=vectordb.as_retriever(search_kwargs={"k": 10}),
        chain_type="stuff",
        return_source_documents=True,
        chain_type_kwargs={
            "prompt": PROMPT
        }
    )


# -------------------------
# File Tree
# -------------------------
def get_file_tree(path):
    tree = ""
    ignored_dirs = {
        ".git", "node_modules", "venv", "__pycache__",
        ".next", "dist", "build", ".idea", ".vscode"
    }

    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]
        level = root.replace(path, "").count(os.sep)
        indent = "  " * level
        folder_name = os.path.basename(root) if os.path.basename(root) else "repo"
        tree += f"{indent}{folder_name}/\n"
        for f in files:
            tree += f"{indent}  {f}\n"
    return tree


# -------------------------
# Project Type Detection
# -------------------------
def detect_project_type(path):
    files = set()
    for root, _, filenames in os.walk(path):
        for f in filenames:
            files.add(f.lower())

    if "package.json" in files:
        if "vite.config.js" in files or "vite.config.ts" in files:
            return "Vite / JavaScript or React Project"
        if "next.config.js" in files:
            return "Next.js Project"
        return "JavaScript / Node.js Project"

    if "requirements.txt" in files or "app.py" in files:
        return "Python Project"

    if "pom.xml" in files:
        return "Java / Maven Project"

    if "cargo.toml" in files:
        return "Rust Project"

    if "go.mod" in files:
        return "Go Project"

    return "Unknown / Mixed Tech Project"


# -------------------------
# Dependency Extraction
# -------------------------
def extract_dependencies(path):
    deps = []

    # package.json
    package_json = os.path.join(path, "package.json")
    if os.path.exists(package_json):
        try:
            with open(package_json, "r", encoding="utf-8") as f:
                data = json.load(f)
                for section in ["dependencies", "devDependencies"]:
                    if section in data:
                        deps.extend(list(data[section].keys()))
        except:
            pass

    # requirements.txt
    requirements = os.path.join(path, "requirements.txt")
    if os.path.exists(requirements):
        try:
            with open(requirements, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        deps.append(line)
        except:
            pass

    # pom.xml (basic parse)
    pom = os.path.join(path, "pom.xml")
    if os.path.exists(pom):
        try:
            with open(pom, "r", encoding="utf-8") as f:
                content = f.read()
                matches = re.findall(r"<artifactId>(.*?)</artifactId>", content)
                deps.extend(matches)
        except:
            pass

    return sorted(list(set(deps)))