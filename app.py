import streamlit as st
import tempfile
import os
import json
import logging
from pathlib import Path

# Add src to pythonpath implicitly since we run this from root
import sys
sys.path.insert(0, os.path.abspath("src"))

from transformer.pipeline import Pipeline

st.set_page_config(
    page_title="Multi-Source Candidate Data Transformer",
    page_icon="🧊",
    layout="wide"
)

st.title("Eightfold Multi-Source Candidate Data Transformer")
st.markdown("""
Upload candidate data from multiple sources (ATS JSON, Recruiter CSV, Resume PDFs, Recruiter Notes TXT, or GitHub URLs) 
and watch the pipeline normalize, merge, and project them into a single canonical JSON profile with full provenance tracking.
""")

st.sidebar.header("Configuration")
config_file = st.sidebar.file_uploader("Upload custom_config.json (Optional)", type=["json"])

# Input Files
st.header("1. Inputs")
uploaded_files = st.file_uploader("Upload Input Files (CSV, JSON, PDF, TXT)", accept_multiple_files=True)
github_url = st.text_input("Or enter a GitHub profile URL (e.g., https://github.com/torvalds)")

# Initialize session state for results
if "results" not in st.session_state:
    st.session_state.results = None

if st.button("Run Pipeline", type="primary"):
    if not uploaded_files and not github_url:
        st.error("Please upload at least one file or enter a GitHub URL.")
    else:
        with st.spinner("Processing pipeline..."):
            # Setup temporary directory for uploaded files
            with tempfile.TemporaryDirectory() as temp_dir:
                input_paths = []
                
                # Save uploaded files
                if uploaded_files:
                    for f in uploaded_files:
                        temp_path = os.path.join(temp_dir, f.name)
                        with open(temp_path, "wb") as out_f:
                            out_f.write(f.getvalue())
                        input_paths.append(temp_path)
                
                # Save github URL to a text file to act like the CLI input
                if github_url:
                    gh_path = os.path.join(temp_dir, "github_profile.txt")
                    with open(gh_path, "w") as out_f:
                        out_f.write(github_url)
                    input_paths.append(gh_path)
                
                # Save config
                config_path = None
                if config_file:
                    config_path = os.path.join(temp_dir, "config.json")
                    with open(config_path, "wb") as out_f:
                        out_f.write(config_file.getvalue())

                # Run pipeline
                try:
                    pipeline = Pipeline()
                    st.session_state.results = pipeline.run_and_serialize(
                        input_paths=input_paths,
                        config_path=config_path,
                        source_types={}
                    )
                except Exception as e:
                    st.error(f"Error running pipeline: {str(e)}")

# Display Results from Session State
if st.session_state.results is not None:
    results = st.session_state.results
    st.success(f"Pipeline completed successfully! Extracted {len(results)} candidate profiles.")
    
    st.header("2. Projected Canonical Profiles")
    
    for i, result in enumerate(results):
        profile = result.get("profile", {})
        validation = result.get("validation", {})
        
        name = profile.get("full_name", f"Candidate {i+1}")
        is_valid = validation.get("valid", True)
        conf = profile.get("overall_confidence", 0)
        
        status_icon = "✅" if is_valid else "❌"
        with st.expander(f"{status_icon} {name} (Confidence: {conf:.2f})", expanded=False):
            # High-level clean UX display
            col1, col2 = st.columns(2)
            
            with col1:
                st.markdown(f"**Candidate ID:** `{profile.get('candidate_id', 'N/A')}`")
                st.markdown(f"**Full Name:** {profile.get('full_name', 'N/A')}")
                
                emails = profile.get("emails", [])
                if emails:
                    st.markdown(f"**Emails:** {', '.join(emails)}")
                    
                phones = profile.get("phones", [])
                if phones:
                    st.markdown(f"**Phones:** {', '.join(phones)}")
                    
            with col2:
                loc = profile.get("location") or {}
                loc_str = ", ".join(filter(None, [loc.get("city"), loc.get("region"), loc.get("country")]))
                st.markdown(f"**Location:** {loc_str or 'N/A'}")
                
                exp = profile.get("years_experience")
                st.markdown(f"**Years of Experience:** {exp if exp is not None else 'N/A'}")
                
                headline = profile.get("headline")
                st.markdown(f"**Headline:** {headline or 'N/A'}")
                
            # Divider
            st.divider()
            
            # Toggle for Raw JSON Schema
            if st.toggle("View Schema (Raw JSON)", key=f"toggle_{i}"):
                st.json(result)
