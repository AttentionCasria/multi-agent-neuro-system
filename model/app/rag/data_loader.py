import os
import logging
from langchain_community.document_loaders import PyPDFLoader
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

logger = logging.getLogger(__name__)

def clean_text(text: str) -> str:
    text = text.replace("\n", "").replace(" ", "")
    text = text.replace("，，", "，").replace("。。", "。")
    return text.strip()

def load_pdfs_from_dir(dir_path: str):
    documents = []
    if not os.path.exists(dir_path):
        logger.warning(f"⚠️ 文档目录不存在: {dir_path}")
        return []
    for filename in os.listdir(dir_path):
        if not filename.lower().endswith(".pdf"):
            continue
        pdf_path = os.path.join(dir_path, filename)
        logger.info(f"📄 加载 PDF: {filename}")
        try:
            loader = PyPDFLoader(pdf_path)
            pages = loader.load()
            for page in pages:
                cleaned = clean_text(page.page_content)
                if len(cleaned) < 50:
                    continue
                documents.append(Document(
                    page_content=cleaned,
                    metadata={
                        "source": filename,
                        "page": page.metadata.get("page", -1)
                    }
                ))
        except Exception as e:
            logger.error(f"❌ 加载 {filename} 失败: {e}")
    logger.info(f"✅ 共加载 {len(documents)} 页医学文档")
    return documents

def split_documents(documents):
    if not documents:
        return []
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=512,
        chunk_overlap=128,
        separators=["\n\n", "。", "；", "\n", " ", ""]
    )
    return splitter.split_documents(documents)

