# test_gdrive.py
import os, streamlit as st

# Minimal shim to read secrets locally without launching Streamlit.
# If running outside Streamlit, you can read TOML yourself. Here we rely on st.secrets.
# Run with: streamlit run test_gdrive.py  (then check terminal logs)
import modules.gdrive as gdrive

def run():
    folder_id = st.secrets["gdrive"]["folder_id"]
    # 1) List files
    files = gdrive.list_files(folder_id)
    print(f"Files in folder: {[f['name'] for f in files]}")
    # 2) Create a temp file and upload
    path = "hello.txt"
    with open(path, "w", encoding="utf-8") as f:
        f.write("Hello Drive!")
    fid = gdrive.upload_file(path, folder_id)
    print("Uploaded file id:", fid)

if __name__ == "__main__":
    run()
