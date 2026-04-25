import os
import base64
import streamlit as st
import shutil
from utils import (
    clone_repo,
    load_documents,
    split_docs,
    create_vectorstore,
    create_qa_chain,
    get_file_tree,
    detect_project_type,
    extract_dependencies
)

# ==========================================
# 🔑 PASTE YOUR GROQ API KEY HERE JUST ONCE
# ==========================================
GROQ_API_KEY = st.secrets["GROQ_API_KEY"]

# -------------------------
# Dynamic Page Config
# -------------------------
logo_path = "logo.png"
# Use the logo file if it exists, otherwise fallback to an emoji for safety
page_icon = logo_path if os.path.exists(logo_path) else "🧠"

st.set_page_config(
    page_title="RepoMind",
    page_icon=page_icon,
    layout="wide"
)

# -------------------------
# Session State Init
# -------------------------
if "qa" not in st.session_state:
    st.session_state.qa = None
if "tree" not in st.session_state:
    st.session_state.tree = None
if "repo_path" not in st.session_state:
    st.session_state.repo_path = None
if "persist_dir" not in st.session_state:
    st.session_state.persist_dir = None
if "project_type" not in st.session_state:
    st.session_state.project_type = None
if "dependencies" not in st.session_state:
    st.session_state.dependencies = []
if "summary" not in st.session_state:
    st.session_state.summary = None
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "last_repo_url" not in st.session_state:
    st.session_state.last_repo_url = ""
if "user_question_trigger" not in st.session_state:
    st.session_state.user_question_trigger = ""

# Callback to handle chat input clearing
def handle_chat():
    st.session_state.user_question_trigger = st.session_state.chat_input
    st.session_state.chat_input = ""

# Helper to encode local image for HTML injection
def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    return None

# -------------------------
# Custom CSS
# -------------------------
st.markdown("""
<style>
    .main-title {
        font-size: 2.5rem;
        font-weight: 800;
        margin-bottom: 0.2rem;
        margin-top: -1rem;
        display: flex;
        align-items: center;
    }
    .subtitle {
        color: #888;
        margin-bottom: 1rem;
    }
    .card {
        padding: 1rem;
        border-radius: 1rem;
        background-color: #111827;
        border: 1px solid #1f2937;
        margin-bottom: 1rem;
        color: #f8fafc;
    }
    .small-title {
        font-size: 1.1rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
    }
    .answer-box {
        background: #0f172a;
        padding: 1rem;
        border-radius: 12px;
        border: 1px solid #334155;
    }
    .stCodeBlock {
        border-radius: 12px !important;
    }
    
    /* Enhanced Input Box Styling */
    .stTextInput div[data-baseweb="input"] {
        background-color: #1e293b !important;
        border: 1px solid #475569 !important;
        border-radius: 8px !important;
    }
    .stTextInput div[data-baseweb="input"]:focus-within {
        border-color: #8b5cf6 !important;
        box-shadow: 0 0 0 1px #8b5cf6 !important;
    }
    .stTextInput input {
        color: #f8fafc !important;
    }
</style>
""", unsafe_allow_html=True)

# -------------------------
# Header & Reset Button Layout
# -------------------------
top_left, top_right = st.columns([4, 1])

with top_left:
    # Process the logo to render inline with the title safely
    logo_b64 = get_base64_image(logo_path)
    if logo_b64:
        # max-height ensures the image never blows up the layout, regardless of its original dimensions
        logo_html = f'<img src="data:image/png;base64,{logo_b64}" style="max-height: 2.2rem; width: auto; object-fit: contain; margin-right: 12px;">'
    else:
        logo_html = "" # Fallback if image goes missing

    st.markdown(f'<div class="main-title">{logo_html}RepoMind</div>', unsafe_allow_html=True)
    st.markdown('<div class="subtitle">Intelligent code analysis and repository exploration.</div>', unsafe_allow_html=True)

with top_right:
    st.write("") # Padding
    if st.button("🧹 Reset RepoMind", use_container_width=True):
        if st.session_state.persist_dir:
            shutil.rmtree(st.session_state.persist_dir, ignore_errors=True)

        # Clear all states
        st.session_state.qa = None
        st.session_state.tree = None
        st.session_state.repo_path = None
        st.session_state.persist_dir = None
        st.session_state.project_type = None
        st.session_state.dependencies = []
        st.session_state.summary = None
        st.session_state.chat_history = []
        st.session_state.last_repo_url = ""
        st.session_state.user_question_trigger = ""
        
        # Clear the UI inputs
        if "repo_url_input" in st.session_state:
            st.session_state.repo_url_input = ""
        if "chat_input" in st.session_state:
            st.session_state.chat_input = ""

        st.rerun()

st.divider()

# -------------------------
# Repo Input
# -------------------------
repo_url = st.text_input(
    "🔗 GitHub Repository URL", 
    placeholder="https://github.com/user/repo",
    key="repo_url_input"
)

# -------------------------
# Analyze Button
# -------------------------
if st.button("🚀 Analyze Repository"):
    if not GROQ_API_KEY or GROQ_API_KEY == "PASTE_YOUR_API_KEY_HERE":
        st.error("⚠️ Please paste your Groq API key at the top of app.py.")
    elif not repo_url:
        st.error("⚠️ Please enter a GitHub repository URL.")
    else:
        with st.spinner("Cloning, indexing, and analyzing the repository..."):
            try:
                # Hard reset if new repo
                if repo_url != st.session_state.last_repo_url:
                    if st.session_state.persist_dir:
                        shutil.rmtree(st.session_state.persist_dir, ignore_errors=True)

                    st.session_state.qa = None
                    st.session_state.tree = None
                    st.session_state.repo_path = None
                    st.session_state.persist_dir = None
                    st.session_state.project_type = None
                    st.session_state.dependencies = []
                    st.session_state.summary = None
                    st.session_state.chat_history = []

                # Process fresh repo
                path = clone_repo(repo_url)
                docs = load_documents(path)

                if not docs:
                    st.error("❌ No readable files found in this repository.")
                    st.stop()

                chunks = split_docs(docs)
                vectordb, persist_dir = create_vectorstore(chunks)
                
                # Fetch tree FIRST so we can feed it to the QA chain
                repo_tree = get_file_tree(path)
                qa = create_qa_chain(vectordb, GROQ_API_KEY, repo_tree)

                # Generate a smart summary using the newly supercharged LLM
                summary_prompt = (
                    "What is the main purpose of this repository? Provide a concise 2-3 paragraph "
                    "summary of what this project actually does, its core features, and its architecture. "
                    "Do NOT include any installation, setup, or deployment instructions. Just summarize the code."
                )
                summary_response = qa.invoke({"query": summary_prompt})

                # Save state
                st.session_state.qa = qa
                st.session_state.tree = repo_tree
                st.session_state.repo_path = path
                st.session_state.persist_dir = persist_dir
                st.session_state.project_type = detect_project_type(path)
                st.session_state.dependencies = extract_dependencies(path)
                st.session_state.summary = summary_response["result"]
                st.session_state.last_repo_url = repo_url

                st.success("✅ Repository analyzed successfully!")

            except Exception as e:
                st.error(f"❌ Failed to process repository:\n\n{e}")

# -------------------------
# Dashboard Layout
# -------------------------
left, right = st.columns([1.1, 1.9])

# -------------------------
# LEFT PANEL
# -------------------------
with left:
    if st.session_state.project_type:
        st.markdown(f"""
        <div class="card">
            <div class="small-title">📌 Project Type</div>
            {st.session_state.project_type}
        </div>
        """, unsafe_allow_html=True)

    if st.session_state.summary:
        # Convert newlines to breaks for clean HTML rendering
        clean_summary = st.session_state.summary.replace("\n", "<br>")
        st.markdown(f"""
        <div class="card">
            <div class="small-title">📝 Project Summary</div>
            <div style="font-size: 0.95rem; line-height: 1.5; color: #cbd5e1;">
                {clean_summary}
            </div>
        </div>
        """, unsafe_allow_html=True)

    if st.session_state.dependencies:
        deps_list = "".join([f"<li>{dep}</li>" for dep in st.session_state.dependencies[:30]])
        st.markdown(f"""
        <div class="card">
            <div class="small-title">📦 Dependencies</div>
            <ul style="margin-top: 0;">
                {deps_list}
            </ul>
        </div>
        """, unsafe_allow_html=True)

    if st.session_state.tree:
        with st.expander("📂 File Tree", expanded=False):
            st.code(st.session_state.tree, language="bash")

    # -------------------------
    # Auto-README Builder
    # -------------------------
    st.markdown("---")
    st.markdown('<div class="small-title">📝 Auto-README Builder</div>', unsafe_allow_html=True)
    
    if st.button("Generate Professional README"):
        if st.session_state.qa is None:
            st.warning("⚠️ Please analyze a repository first.")
        else:
            with st.spinner("Drafting a beautiful README.md..."):
                try:
                    readme_prompt = """
                    Write a professional, comprehensive README.md file for this repository.
                    Use the following structure:
                    1. Project Title and short description
                    2. Table of Contents
                    3. Features
                    4. Tech Stack (Infer from dependencies)
                    5. Installation (Provide standard commands based on the project type)
                    6. Usage (How to run it)
                    7. Project Structure (Briefly explain the main folders)
                    
                    Use standard Markdown formatting. Do not include any chatty dialogue, just output the raw Markdown.
                    """
                    
                    response = st.session_state.qa.invoke({"query": readme_prompt})
                    generated_readme = response["result"]
                    
                    st.success("✅ README generated!")
                    
                    with st.expander("👀 Preview README", expanded=True):
                        st.markdown(generated_readme)
                        
                    st.download_button(
                        label="⬇️ Download README.md",
                        data=generated_readme,
                        file_name="README.md",
                        mime="text/markdown",
                        type="primary"
                    )

                except Exception as e:
                    st.error(f"❌ Failed to generate README:\n\n{e}")

# -------------------------
# RIGHT PANEL
# -------------------------
with right:
    st.subheader("💬 Ask RepoMind")

    st.text_input(
        "Ask anything about the repository",
        placeholder="e.g. Which file is the entry point?",
        key="chat_input",
        on_change=handle_chat
    )

    user_question = st.session_state.user_question_trigger

    if user_question:
        if st.session_state.qa is None:
            st.warning("⚠️ Please analyze a repository first.")
            st.session_state.user_question_trigger = ""
        else:
            with st.spinner("Thinking..."):
                try:
                    response = st.session_state.qa.invoke({"query": user_question})
                    answer = response["result"]

                    st.session_state.chat_history.append({
                        "question": user_question,
                        "answer": answer,
                        "sources": response.get("source_documents", [])
                    })

                except Exception as e:
                    st.error(f"❌ Failed to answer question:\n\n{e}")
            
            st.session_state.user_question_trigger = ""

    # -------------------------
    # Chat History
    # -------------------------
    if st.session_state.chat_history:
        st.markdown("## Conversation History")
        for item in reversed(st.session_state.chat_history):
            st.markdown("### ❓ Question")
            st.write(item["question"])

            st.markdown("### ✅ Answer")
            st.markdown(f'<div class="answer-box">{item["answer"]}</div>', unsafe_allow_html=True)

            with st.expander("📂 Show Source Files Used"):
                shown = set()
                for doc in item["sources"]:
                    src = doc.metadata.get("source", "")
                    if src and src not in shown:
                        shown.add(src)
                        st.code(src)
            st.divider()
