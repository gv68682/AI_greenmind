import os
import time
import requests
import streamlit as st
import logging
import re
import pickle
import unicodedata
from typing import List
from langchain_core.documents import Document

# ─────────────────────────────────────────────
# Imports
# ─────────────────────────────────────────────
try:
    from langchain_community.vectorstores import FAISS
    from langchain_huggingface import HuggingFaceEmbeddings
    from langchain_community.document_loaders import PyPDFLoader
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    from rank_bm25 import BM25Okapi
    LANGCHAIN_AVAILABLE = True
    print("DEBUG — langchain_community: AVAILABLE ✅")
except ImportError as e:
    LANGCHAIN_AVAILABLE = False
    print(f"DEBUG — langchain_community: FAILED ❌ {e}")

# ─────────────────────────────────────────────
# Logger
# ─────────────────────────────────────────────
log_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "ragchunks.log"
)
logging.basicConfig(
    filename=log_path,
    filemode='w',
    format='%(message)s',
    level=logging.INFO
)
rag_logger = logging.getLogger("ragchunks")


# ─────────────────────────────────────────────
# Text Cleaning + Structure
# ─────────────────────────────────────────────
def is_heading(line: str) -> bool:
    line = line.strip()
    return bool(re.match(r"^(article|section|\d+\.|chapter|part)\b", line.lower()))


def clean_and_structure(text: str) -> str:
    if not text:
        return ""
    
    # Remove page number patterns like "- 6 -", "- 12 -", "Page 6", "6 of 45"
    text = re.sub(r"-\s*\d+\s*-", "", text)
    text = re.sub(r"page\s+\d+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\d+\s+of\s+\d+", "", text, flags=re.IGNORECASE)
    # Remove standalone page numbers at line start
    text = re.sub(r"^\d+\s*\n", "", text, flags=re.MULTILINE)
    text = re.sub(r"\b\d+\s*-\s*\d+\b", "", text)
    
    # fix hyphenation
    text = re.sub(r"(\w+)-\n(\w+)", r"\1\2", text)
    # normalize newlines
    text = re.sub(r"\n+", "\n", text)
    text = re.sub(r"\s+", " ", text)
    
    # Fix merged section labels
    text = re.sub(r"(Section\s+\d+)(Section\s+\d+)", r"\1 \2", text)
    text = re.sub(r"(Chapter\s+\d+)(Chapter\s+\d+)", r"\1 \2", text)

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    structured = []
    buffer = []
    for line in lines:
        if is_heading(line):
            if buffer:
                structured.append(" ".join(buffer))
                buffer = []
            structured.append("\n" + line + "\n")
        else:
            buffer.append(line)
    if buffer:
        structured.append(" ".join(buffer))
    return "\n".join(structured)


def is_index_page(text: str) -> bool:
    numbers = len(re.findall(r'\d+', text))
    words   = len(re.findall(r'[a-zA-Z]{4,}', text))
    has_index_keyword = "index" in text.lower() or "references" in text.lower()
    is_number_heavy = numbers > words
    return is_number_heavy and has_index_keyword


# ─────────────────────────────────────────────
# Metadata Detection
# ─────────────────────────────────────────────
def detect_chapter(text: str) -> str:
    patterns = [
        r"chapter\s+\d+",
        r"section\s+[a-z0-9\.]+",
        r"article\s+\d+",
        r"summary for policymakers",
        r"technical summary",
        r"annex\s+\d+"
    ]
    text_lower = text.lower()
    for p in patterns:
        match = re.search(p, text_lower)
        if match:
            return match.group(0)
    return "unknown"


def detect_section(text: str) -> str:
    match = re.search(r"(section|part|chapter)\s+[a-z0-9\.]+", text.lower())
    return match.group(0) if match else "unknown"


def detect_source_type(url: str) -> str:
    if "ipcc" in url:
        return "IPCC"
    elif "unep" in url or "wedocs" in url:
        return "UNEP"
    elif "who" in url:
        return "WHO"
    elif "fao" in url:
        return "FAO"
    elif "undp" in url:
        return "UNDP"
    elif "cbd" in url:
        return "CBD"
    elif "unfccc" in url:
        return "UNFCCC"
    elif "resourcepanel" in url:
        return "UNEP-IRP"
    else:
        return "OTHER"


# ─────────────────────────────────────────────
# Hybrid Retriever — FAISS + BM25
# ─────────────────────────────────────────────
class HybridRetriever:
    """
    Combines FAISS (semantic) + BM25 (keyword) retrieval.
    Merges and deduplicates results, optionally reranks.
    """

    def __init__(self, documents: List[Document], embeddings, k: int = 8):
        self.documents = documents
        self.k = k

        # Build FAISS
        self.vectordb = FAISS.from_documents(documents, embeddings)

        # Build BM25
        tokenized = [doc.page_content.lower().split() for doc in documents]
        self.bm25 = BM25Okapi(tokenized)

    def retrieve(self, query: str, k: int = None) -> List[Document]:
        k = k or self.k

        # FAISS semantic search
        faiss_results = self.vectordb.similarity_search(query, k=k)

        # BM25 keyword search
        tokenized_query = query.lower().split()
        bm25_scores = self.bm25.get_scores(tokenized_query)
        top_bm25_indices = sorted(
            range(len(bm25_scores)),
            key=lambda i: bm25_scores[i],
            reverse=True
        )[:k]
        bm25_results = [self.documents[i] for i in top_bm25_indices]

        # Merge + deduplicate by content
        seen = set()
        merged = []
        for doc in faiss_results + bm25_results:
            key = doc.page_content[:100]
            if key not in seen:
                seen.add(key)
                merged.append(doc)

        # Optional reranking hook
        #merged = self._rerank(query, merged, top_k=k)

        return merged[:k]

    # def _rerank(self, query: str, docs: List[Document], top_k: int) -> List[Document]:
    #     """
    #     Reranking hook — uses cross-encoder if available,
    #     falls back to BM25 score ordering.
    #     """
    #     try:
    #         from sentence_transformers import CrossEncoder
    #         model = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
    #         pairs = [[query, doc.page_content] for doc in docs]
    #         scores = model.predict(pairs)
    #         ranked = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)
    #         return [doc for _, doc in ranked[:top_k]]
    #     except Exception:
    #         # Fallback — return as is
    #         return docs[:top_k]

    def save_local(self, path: str):
        self.vectordb.save_local(path)

    @classmethod
    def load_local(cls, path: str, embeddings, documents: List[Document] = None, k: int = 8):
        """Load from cached FAISS. BM25 rebuilt from documents if provided."""
        instance = cls.__new__(cls)
        instance.k = k
        instance.vectordb = FAISS.load_local(
            path, embeddings, allow_dangerous_deserialization=True
        )
        if documents:
            instance.documents = documents
            tokenized = [doc.page_content.lower().split() for doc in documents]
            instance.bm25 = BM25Okapi(tokenized)
        else:
            # BM25 not available without documents — FAISS only
            instance.documents = []
            instance.bm25 = None
        return instance

    def similarity_search(self, query: str, k: int = None) -> List[Document]:
        """Drop-in replacement for vectordb.similarity_search()"""
        if self.bm25:
            return self.retrieve(query, k=k or self.k)
        else:
            return self.vectordb.similarity_search(query, k=k or self.k)


# ─────────────────────────────────────────────
# 1. Read URLs from text file
# ─────────────────────────────────────────────
def load_urls_from_file(filepath: str) -> list[str]:
    with open(filepath, "r") as f:
        urls = [line.strip() for line in f.readlines() if line.strip()]
    return urls


# ─────────────────────────────────────────────
# 2. Download PDF with retry
# ─────────────────────────────────────────────
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
                pdf_url, headers=headers, timeout=60, stream=True
            )
            response.raise_for_status()

            with open(temp_filename, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            if not os.path.exists(temp_filename) or \
               os.path.getsize(temp_filename) == 0:
                raise ValueError("Downloaded file is empty")

            with open(temp_filename, "rb") as f:
                header = f.read(5)

            if not header.startswith(b"%PDF"):
                raise ValueError(
                    f"URL returned HTML/webpage, not a PDF. "
                    f"Got header: {header}"
                )
            return True

        except Exception as e:
            if attempt < retries:
                time.sleep(delay)
            continue

    return False



# ─────────────────────────────────────────────
# 3. Load + chunk a single PDF
# ─────────────────────────────────────────────
def load_pdf_chunks(pdf_url: str, temp_filename: str = "temp.pdf") -> List[Document]:
    if not LANGCHAIN_AVAILABLE:
        raise RuntimeError("PDF loading not available in this environment.")

    success = download_pdf_with_retry(pdf_url, temp_filename)
    if not success:
        raise ValueError(f"Failed to download after all retries: {pdf_url}")

    source_type = detect_source_type(pdf_url)

    try:
        loader = PyPDFLoader(temp_filename)
        docs = loader.load()

        # 1. Clean
        for doc in docs:
            doc.page_content = clean_and_structure(doc.page_content)

        # 2. Filter
        docs = [doc for doc in docs
                if len(doc.page_content.strip()) > 150
                and not is_index_page(doc.page_content)]

        if not docs:
            raise ValueError("PDF loaded but no content extracted.")

        # 3. Log — now reflects exactly what goes into vectorstore
        rag_logger.info(f"URL    : {pdf_url}")
        rag_logger.info(f"Source : {source_type}")
        rag_logger.info(f"Pages  : {len(docs)}")
        for doc in docs:
            page_num = (doc.metadata.get("page") or 0) + 1
            rag_logger.info(f"Page {page_num}: {doc.page_content[:80]}")

    except Exception as e:
        raise ValueError(f"PDF parsing failed: {str(e)}")

    finally:
        if os.path.exists(temp_filename):
            os.remove(temp_filename)

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=1200,
        chunk_overlap=200,
        separators=["\n\n", "\n", ".", " "]
    )
    chunks = splitter.split_documents(docs)

    # Tag each chunk with metadata
    for chunk in chunks:
        chunk.metadata.update({
            "source_url":   pdf_url,
            "source_type":  source_type,
            "chapter":      detect_chapter(chunk.page_content),
            "section":      detect_section(chunk.page_content),
            "page":         chunk.metadata.get("page", 0)
        })

    return chunks


# ─────────────────────────────────────────────
# 4. Build ONE HybridRetriever from a list of URLs
# ─────────────────────────────────────────────
def build_vectorstore_from_urls(urls: list[str], store_name: str) -> HybridRetriever:

    embeddings = HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-mpnet-base-v2"
    )
    all_documents = []

    progress_bar = st.progress(0)
    for i, url in enumerate(urls):
        progress_bar.progress((i + 1) / len(urls))
        try:
            chunks = load_pdf_chunks(url, temp_filename=f"temp_{store_name}.pdf")
            all_documents.extend(chunks)
            rag_logger.info(f"✅{len(chunks)} chunks {i+1}/{len(urls)}: {url}")
            rag_logger.info("=" * 80 + "\n")
            rag_logger.info("=" * 80)
        except Exception as e:
            rag_logger.info(f"❌ Failed PDF {i+1}/{len(urls)}: {url} — {e}")
            rag_logger.info("=" * 80 + "\n")
            rag_logger.info("=" * 80)
            continue

    progress_bar.empty()

    retriever = HybridRetriever(all_documents, embeddings)
    return retriever


# ─────────────────────────────────────────────
# 5. Build BOTH retrievers — Streamlit cached
# ─────────────────────────────────────────────
@st.cache_resource
def build_both_vectorstores(txt_file_1, txt_file_2):

    BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cache_path_1 = os.path.join(BASE_DIR, "vectorstore_cache", "Environmental_Policies")
    cache_path_2 = os.path.join(BASE_DIR, "vectorstore_cache", "Environmental_Effects")

    # ✅ Debug — see what path Streamlit is looking at
    # print(f"DEBUG — BASE_DIR     : {BASE_DIR}")
    # print(f"DEBUG — cache_path_1 : {cache_path_1}")
    # print(f"DEBUG — exists_1     : {os.path.exists(cache_path_1)}")
    # print(f"DEBUG — exists_2     : {os.path.exists(cache_path_2)}")

    use_cache = os.getenv("USE_CACHE", "true").lower() == "true"

    if use_cache and os.path.exists(cache_path_1) and os.path.exists(cache_path_2):
        embeddings = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-mpnet-base-v2"
        )
            # Load documents for BM25
        with open(os.path.join(cache_path_1, "documents.pkl"), "rb") as f:
            docs_1 = pickle.load(f)
        with open(os.path.join(cache_path_2, "documents.pkl"), "rb") as f:
            docs_2 = pickle.load(f)

        vectordb_1 = HybridRetriever.load_local(cache_path_1, embeddings, documents=docs_1)
        vectordb_2 = HybridRetriever.load_local(cache_path_2, embeddings, documents=docs_2)
        return vectordb_1, vectordb_2

    if not LANGCHAIN_AVAILABLE:
        st.error("❌ Cannot build vectorstore — langchain_community not available.")
        st.stop()

    urls_1     = load_urls_from_file(txt_file_1)
    urls_2     = load_urls_from_file(txt_file_2)
    vectordb_1 = build_vectorstore_from_urls(urls_1, "Environmental_Policies")
    vectordb_2 = build_vectorstore_from_urls(urls_2, "Environmental_Effects")

    # Save FAISS cache
    os.makedirs(cache_path_1, exist_ok=True)
    os.makedirs(cache_path_2, exist_ok=True)
    vectordb_1.save_local(cache_path_1)
    vectordb_2.save_local(cache_path_2)

    # Save documents for BM25 rebuild
    with open(os.path.join(cache_path_1, "documents.pkl"), "wb") as f:
        pickle.dump(vectordb_1.documents, f)
    with open(os.path.join(cache_path_2, "documents.pkl"), "wb") as f:
        pickle.dump(vectordb_2.documents, f)

    return vectordb_1, vectordb_2