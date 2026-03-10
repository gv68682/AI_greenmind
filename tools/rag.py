import os
import time
import requests
import streamlit as st
from langchain_community.document_loaders import PyPDFLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_community.vectorstores import FAISS


# ─────────────────────────────────────────────
# 1. Read URLs from text file
# ─────────────────────────────────────────────
def load_urls_from_file(filepath: str) -> list[str]:
    with open(filepath, "r") as f:
        urls = [line.strip() for line in f.readlines() if line.strip()]
    return urls


def download_pdf_with_retry(
    pdf_url: str,
    temp_filename: str,
    retries: int = 3,
    delay: int = 5
) -> bool:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept":          "application/pdf,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection":      "keep-alive",
        "Referer":         "https://www.google.com/"
    }

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(
                pdf_url,
                headers=headers,
                timeout=60,
                stream=True
            )
            response.raise_for_status()

            with open(temp_filename, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            if not os.path.exists(temp_filename) or \
               os.path.getsize(temp_filename) == 0:
                raise ValueError("Downloaded file is empty", temp_filename, pdf_url)

            with open(temp_filename, "rb") as f:
                header = f.read(5)

            if not header.startswith(b"%PDF"):
                raise ValueError(
                    f"URL returned HTML/webpage, not a PDF.\n"
                    f"Got header: {header}\n"
                    f"URL needs replacement: {pdf_url}"
                )

            return True

        except Exception as e:
            # st.warning(f"  ⚠️ Attempt {attempt}/{retries} failed: {str(e)[:120]}")
            if attempt < retries:
                time.sleep(delay)
            continue

    return False


def load_pdf_chunks(pdf_url: str, temp_filename: str = "temp.pdf"):
    success = download_pdf_with_retry(pdf_url, temp_filename)

    if not success:
        raise ValueError(f"Failed to download after all retries: {pdf_url}")

    try:
        loader = PyPDFLoader(temp_filename)
        docs   = loader.load()

        if not docs:
            raise ValueError("PDF loaded but no content extracted.")

    except Exception as e:
        raise ValueError(f"PDF parsing failed: {str(e)}")

    finally:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1000,
        chunk_overlap=100,
    )

    return splitter.split_documents(docs)


# ─────────────────────────────────────────────
# 3. Build ONE vectorstore from a list of URLs
# ─────────────────────────────────────────────
def build_vectorstore_from_urls(urls: list[str], store_name: str) -> FAISS:

    # st.write(f"📚 Building vector store: **[{store_name}]** — {len(urls)} PDFs...")

    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/multi-qa-MiniLM-L6-cos-v1"
    )
    all_documents = []

    # progress_bar = st.progress(0, text=f"Loading PDFs for {store_name}...")

    # for i, url in enumerate(urls):
    #     progress_bar.progress(
    #         (i + 1) / len(urls),
    #         text=f"⏳ [{store_name}] Loading PDF {i+1}/{len(urls)}..."
    #     )

    progress_bar = st.progress(0)
    for i, url in enumerate(urls):
        progress_bar.progress(
            (i + 1) / len(urls)
        )
        try:
            chunks = load_pdf_chunks(url, temp_filename=f"temp_{store_name}.pdf")
            all_documents.extend(chunks)
            # st.write(f"  ✅ PDF {i+1} loaded — {len(chunks)} chunks")
        except Exception as e:
            # st.warning(f"  ❌ Failed to load PDF {i+1}: {e}")
            continue

    progress_bar.empty()

    vectordb = FAISS.from_documents(all_documents, embeddings)
    # st.success(f"✅ [{store_name}] ready — {len(all_documents)} total chunks.")
    return vectordb


# ─────────────────────────────────────────────
# 4. Build BOTH vectorstores — Streamlit cached
# ─────────────────────────────────────────────
@st.cache_resource
def build_both_vectorstores(txt_file_1, txt_file_2):

    BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_path_1 = os.path.join(BASE_DIR, "vectorstore_cache", "Environmental_Policies")
    cache_path_2 = os.path.join(BASE_DIR, "vectorstore_cache", "Environmental_Effects")

    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/multi-qa-MiniLM-L6-cos-v1"
    )

    # ✅ Load from cache if exists — instant
    if os.path.exists(cache_path_1) and os.path.exists(cache_path_2):
        vectordb_1 = FAISS.load_local(
            cache_path_1, embeddings,
            allow_dangerous_deserialization=True
        )
        vectordb_2 = FAISS.load_local(
            cache_path_2, embeddings,
            allow_dangerous_deserialization=True
        )
        st.success("🌿 GreenMind is ready!")
        return vectordb_1, vectordb_2

    # Fallback — build from scratch if cache missing
    urls_1 = load_urls_from_file(txt_file_1)
    urls_2 = load_urls_from_file(txt_file_2)
    vectordb_1 = build_vectorstore_from_urls(urls_1, "Environmental_Policies")
    vectordb_2 = build_vectorstore_from_urls(urls_2, "Environmental_Effects")

    st.success("🌿 GreenMind is ready!")
    return vectordb_1, vectordb_2