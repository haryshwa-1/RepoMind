import os
import base64
import streamlit as st
import shutil
import json
from utils import (
    clone_repo,
    load_documents,
    split_docs,
    create_vectorstore,
    create_qa_chain,
    get_file_tree,
    detect_project_type,
    extract_dependencies,
    run_semgrep,              
    parse_semgrep_output,     
    run_scout_agent,          
    run_verifier_agent        
)

# ==========================================
# 🔑 PASTE YOUR GROQ API KEY HERE JUST ONCE
# ==========================================
GROQ_API_KEY = ""

# -------------------------
# Dynamic Page Config
# -------------------------
logo_path = "logo.png"
page_icon = logo_path if os.path.exists(logo_path) else "🛡️"

st.set_page_config(
    page_title="RepoMind",
    page_icon=page_icon,
    layout="wide"
)

# -------------------------
# Session State Init
# -------------------------
state_defaults = {
    "vectordb": None, 
    "qa": None, 
    "tree": None, 
    "repo_path": None, 
    "persist_dir": None, 
    "project_type": None, 
    "dependencies": [], 
    "summary": None, 
    "security_report": None, 
    "verification_report": None, 
    "raw_json": None, 
    "chat_history": [], 
    "last_repo_url": "",
    "user_question_trigger": "",
    "chat_input": ""
    # Notice 'security_mode' is NOT in here anymore
}

for key, default_value in state_defaults.items():
    if key not in st.session_state:
        st.session_state[key] = default_value

# -------------------------
# Helper Functions
# -------------------------
def reset_environment():
    """Helper to cleanly wipe files and state without crashing widgets."""
    if st.session_state.persist_dir:
        shutil.rmtree(st.session_state.persist_dir, ignore_errors=True)
    if st.session_state.repo_path:
        shutil.rmtree(st.session_state.repo_path, ignore_errors=True)
    
    # Reset ONLY the data keys, not the widget keys
    for key in state_defaults.keys():
        st.session_state[key] = state_defaults[key]
    
    # DO NOT use del st.session_state[key] or touch 'security_mode' here

def handle_chat():
    st.session_state.user_question_trigger = st.session_state.chat_input
    st.session_state.chat_input = ""

def get_base64_image(image_path):
    if os.path.exists(image_path):
        with open(image_path, "rb") as img_file:
            return base64.b64encode(img_file.read()).decode()
    return None

def generate_markdown_report():
    repo = st.session_state.last_repo_url
    phase3 = st.session_state.verification_report or "No Phase 3 data."
    phase2 = st.session_state.security_report or "No Phase 2 data."
    phase1 = json.dumps(st.session_state.raw_json, indent=2) if st.session_state.raw_json else "No Phase 1 data."
    
    ticks = "```"
    report = f"# RepoMind Multi-Pass SAST Audit\n**Target Repository:** {repo}\n\n---\n\n"
    report += f"## ✅ Phase 3: Context Verifier (Global Architecture Analysis)\n{phase3}\n\n---\n\n"
    report += f"## 🕵️‍♂️ Phase 2: Logic Scout (Initial Triage)\n{phase2}\n\n---\n\n"
    report += f"## ⚙️ Phase 1: Deterministic Engine (Raw Semgrep Output)\n{ticks}json\n{phase1}\n{ticks}\n"
    return report

# -------------------------
# Custom CSS
# -------------------------
st.markdown("""
<style>
    .main-title { font-size: 2.5rem; font-weight: 800; margin-bottom: 0.2rem; margin-top: -1rem; display: flex; align-items: center; }
    .subtitle { color: #888; margin-bottom: 1rem; }
    .card { padding: 1rem; border-radius: 1rem; background-color: #111827; border: 1px solid #1f2937; margin-bottom: 1rem; color: #f8fafc; }
    .small-title { font-size: 1.1rem; font-weight: 700; margin-bottom: 0.5rem; }
    .answer-box { background: #0f172a; padding: 1rem; border-radius: 12px; border: 1px solid #334155; }
    .stCodeBlock { border-radius: 12px !important; }
    .stTextInput div[data-baseweb="input"] { background-color: #1e293b !important; border: 1px solid #475569 !important; border-radius: 8px !important; }
    .stTextInput div[data-baseweb="input"]:focus-within { border-color: #8b5cf6 !important; box-shadow: 0 0 0 1px #8b5cf6 !important; }
    .stTextInput input { color: #f8fafc !important; }
</style>
""", unsafe_allow_html=True)

# -------------------------
# Header & Reset Button Layout
# -------------------------
is_sast = st.session_state.get("security_mode", False)

top_left, top_right = st.columns([4, 1])

with top_left:
    logo_b64 = get_base64_image(logo_path)
    logo_html = f'<img src="data:image/png;base64,{logo_b64}" style="max-height: 2.2rem; width: auto; object-fit: contain; margin-right: 12px;">' if logo_b64 else ""
    
    if is_sast:
        st.markdown(f'<div class="main-title">{logo_html}RepoMind SAST</div>', unsafe_allow_html=True)
        st.markdown('<div class="subtitle">Multi-Pass Agentic Security Framework.</div>', unsafe_allow_html=True)
    else:
        st.markdown(f'<div class="main-title">{logo_html}RepoMind</div>', unsafe_allow_html=True)
        st.markdown('<div class="subtitle">Intelligent code analysis and repository exploration.</div>', unsafe_allow_html=True)

with top_right:
    st.write("") # Padding
    if st.button("🧹 Reset Framework", use_container_width=True):
        reset_environment()
        st.rerun()

st.divider()

# -------------------------
# Input Elements
# -------------------------
col1, col2 = st.columns([3, 1])
with col1:
    repo_url = st.text_input(
        "🔗 GitHub Repository URL", 
        placeholder="[https://github.com/user/repo](https://github.com/user/repo)",
        key="repo_url_input"
    )
with col2:
    st.markdown("<div style='margin-top: 28px;'></div>", unsafe_allow_html=True)
    st.toggle("🛡️ Enable Security Audit Mode", key="security_mode")

# -------------------------
# Analyze Button Logic
# -------------------------
if st.button("🚀 Analyze Repository"):
    if not GROQ_API_KEY or GROQ_API_KEY == "PASTE_YOUR_API_KEY_HERE":
        st.error("⚠️ Please set your GROQ API key at the top of app.py.")
    elif not repo_url:
        st.error("⚠️ Please enter a GitHub repository URL.")
    else:
        with st.spinner("Initializing Pipeline..."):
            try:
                # Hard reset if new repo
                if repo_url != st.session_state.last_repo_url:
                    reset_environment()

                path = clone_repo(repo_url)
                st.session_state.repo_path = path
                st.session_state.tree = get_file_tree(path)
                st.session_state.project_type = detect_project_type(path)
                st.session_state.dependencies = extract_dependencies(path)
                st.session_state.last_repo_url = repo_url
                
                status_placeholder = st.empty()
                status_placeholder.info("Indexing codebase into Vector Database...")
                docs = load_documents(path)
                
                if not docs:
                    status_placeholder.error("❌ No readable files found in this repository.")
                    st.stop()
                    
                chunks = split_docs(docs)
                vectordb, persist_dir = create_vectorstore(chunks)
                st.session_state.vectordb = vectordb
                st.session_state.persist_dir = persist_dir

                if is_sast:
                    # ==========================================
                    # SAST Pipeline Execution (Corrected for Compatibility)
                    # ==========================================
                    status_placeholder.info("Phase 1: Running Deterministic SAST Engine (Semgrep)...")
                    raw_sast_data = run_semgrep(path)
                    st.session_state.raw_json = raw_sast_data 

                    if "error" in raw_sast_data:
                        status_placeholder.error("🚨 Phase 1 Failed. Review raw JSON data below.")
                    else:
                        parsed_data = parse_semgrep_output(raw_sast_data)
                        status_placeholder.info("Phase 2: Running Logic Scout Agent (Triage)...")
                        
                        # UNPACK BOTH VALUES: The UI report and the filtered data list
                        scout_report, filtered_data = run_scout_agent(parsed_data, GROQ_API_KEY)
                        st.session_state.security_report = scout_report

                        if not filtered_data:
                            status_placeholder.success("✅ Multi-Pass Complete! No survivors from Phase 2.")
                            st.session_state.verification_report = "No alerts survived Phase 2 triage."
                        else:
                            status_placeholder.info(f"Phase 3: Verifying {len(filtered_data)} alerts with Global Context...")
                            
                            # PASS THE FILTERED DATA: Not the original parsed_data
                            verifier_report = run_verifier_agent(
                                filtered_data, 
                                st.session_state.vectordb, 
                                GROQ_API_KEY
                            )
                            st.session_state.verification_report = verifier_report
                            status_placeholder.success("✅ Multi-Pass Verification Complete!")
                else:
                    # ==========================================
                    # Standard QA Pipeline Execution
                    # ==========================================
                    st.session_state.qa = create_qa_chain(
                        vectordb, 
                        GROQ_API_KEY, 
                        st.session_state.tree, 
                        security_mode=False
                    )

                    summary_prompt = (
                        "What is the main purpose of this repository? Provide a concise 2-3 paragraph "
                        "summary of what this project actually does, its core features, and its architecture. "
                        "Do NOT include any installation, setup, or deployment instructions. Just summarize the code."
                    )
                    summary_response = st.session_state.qa.invoke({"query": summary_prompt})
                    st.session_state.summary = summary_response["result"]
                    status_placeholder.success("✅ Repository analyzed successfully!")

            except Exception as e:
                st.error(f"❌ Failed to process repository:\n\n{e}")

# -------------------------
# Dashboard Layout
# -------------------------
left, right = st.columns([1.1, 1.9])

# -------------------------
# LEFT PANEL (Metadata)
# -------------------------
with left:
    if st.session_state.project_type:
        st.markdown(f'<div class="card"><div class="small-title">📌 Project Type</div>{st.session_state.project_type}</div>', unsafe_allow_html=True)
    if st.session_state.dependencies:
        deps_list = "".join([f"<li>{dep}</li>" for dep in st.session_state.dependencies[:30]])
        st.markdown(f'<div class="card"><div class="small-title">📦 Dependencies</div><ul style="margin-top: 0;">{deps_list}</ul></div>', unsafe_allow_html=True)
    if st.session_state.tree:
        with st.expander("📂 File Tree", expanded=False):
            st.code(st.session_state.tree, language="bash")

    # Auto-README Builder (Only show in standard mode)
    if not is_sast and st.session_state.qa:
        st.markdown("---")
        st.markdown('<div class="small-title">📝 Auto-README Builder</div>', unsafe_allow_html=True)
        
        if st.button("Generate Professional README"):
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
# RIGHT PANEL (Content)
# -------------------------
with right:
    if is_sast:
        # --- SAST UI VIEW ---
        if st.session_state.verification_report:
            st.subheader("✅ Phase 3: Verifier Agent (Global Context)")
            st.markdown(st.session_state.verification_report, unsafe_allow_html=True)
            st.divider()

            with st.expander("🕵️‍♂️ View Phase 2: Logic Scout Initial Triage"):
                st.markdown(st.session_state.security_report)

            with st.expander("⚙️ View Phase 1: Raw Deterministic Data"):
                st.json(st.session_state.raw_json)
                
            st.divider()
            repo_name = st.session_state.last_repo_url.split("/")[-1] if st.session_state.last_repo_url else "audit"
            st.download_button(
                label="📥 Export Research Data (.md)",
                data=generate_markdown_report(),
                file_name=f"repomind_{repo_name}_audit.md",
                mime="text/markdown",
                use_container_width=True
            )
        elif st.session_state.raw_json and "error" in st.session_state.raw_json:
            st.subheader("🚨 Pipeline Halted at Phase 1")
            st.json(st.session_state.raw_json)
        elif st.session_state.repo_path:
            st.warning("⚠️ Please click 'Analyze Repository' to execute the pipeline.")
            
    else:
        # --- STANDARD UI VIEW ---
        if st.session_state.summary:
            st.subheader("📝 Project Summary")
            clean_summary = st.session_state.summary.replace("\n", "<br>")
            st.markdown(f'<div class="answer-box" style="margin-bottom: 2rem;">{clean_summary}</div>', unsafe_allow_html=True)

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
