
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import PyPDFLoader
import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from oru_robot.models.model_factory import chat_model, embed_model
from utils.logger_handler import logger


class APIRAGService:
    def __init__(self, config=None):
        self.config = config or {
            "collection_name": "api_reference",
            "persist_directory": "oru_robot/data/knowledge_base/chroma_db",
            "chunk_size": 1000,
            "chunk_overlap": 200,
            "search_k": 5
        }
        
        self.vector_store = None
        self.retriever = None
        self.chain = None
        self._init_vector_store()
        self._init_chain()

    def _init_vector_store(self):
        os.makedirs(self.config["persist_directory"], exist_ok=True)
        
        self.vector_store = Chroma(
            collection_name=self.config["collection_name"],
            embedding_function=embed_model,
            persist_directory=self.config["persist_directory"],
        )
        
        self.retriever = self.vector_store.as_retriever(
            search_kwargs={"k": self.config["search_k"]}
        )

    def _init_chain(self):
        prompt_text = """你是一个专业的机器人API文档助手。请根据以下参考资料回答用户的问题。

参考资料：
{context}

用户问题：{input}

请给出准确、详细的回答，包括：
1. API函数名称
2. 参数说明
3. 使用示例
4. 注意事项

如果参考资料中没有相关信息，请明确说明。"""

        prompt_template = PromptTemplate.from_template(prompt_text)
        self.chain = prompt_template | chat_model | StrOutputParser()

    def load_pdf_documents(self, pdf_paths):
        all_documents = []
        
        for pdf_path in pdf_paths:
            if not os.path.exists(pdf_path):
                logger.warning(f"[RAG] PDF文件不存在: {pdf_path}")
                continue
            
            try:
                loader = PyPDFLoader(pdf_path)
                documents = loader.load()
                
                for doc in documents:
                    doc.metadata["source"] = os.path.basename(pdf_path)
                
                all_documents.extend(documents)
                logger.info(f"[RAG] 成功加载PDF: {pdf_path}, 共{len(documents)}页")
                
            except Exception as e:
                logger.error(f"[RAG] 加载PDF失败 {pdf_path}: {str(e)}", exc_info=True)
        
        if all_documents:
            self._split_and_add_documents(all_documents)

    def _split_and_add_documents(self, documents):
        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=self.config["chunk_size"],
            chunk_overlap=self.config["chunk_overlap"],
            separators=["\n\n", "\n", ".", "!", "?", ",", " ", ""],
        )
        
        split_docs = text_splitter.split_documents(documents)
        
        if split_docs:
            self.vector_store.add_documents(split_docs)
            logger.info(f"[RAG] 成功添加 {len(split_docs)} 个文档片段到向量库")

    def retrieve_docs(self, query):
        return self.retriever.invoke(query)

    def query(self, question: str):
        context_docs = self.retrieve_docs(question)
        
        if not context_docs:
            return "抱歉，没有找到相关的API文档信息。"
        
        context = ""
        for i, doc in enumerate(context_docs, 1):
            context += f"【参考资料{i}】\n来源: {doc.metadata.get('source', '未知')}\n内容: {doc.page_content}\n\n"
        
        return self.chain.invoke({
            "input": question,
            "context": context
        })

    def clear_vector_store(self):
        if self.vector_store:
            self.vector_store.delete_collection()
            logger.info("[RAG] 向量库已清空")
            self._init_vector_store()


if __name__ == '__main__':
    rag_service = APIRAGService()
    
    pdf_files = [
        "API_Reference_Control.pdf",
        "API_Reference_Receive.pdf"
    ]
    
    print("正在加载API文档...")
    rag_service.load_pdf_documents(pdf_files)
    
    print("\n测试查询:")
    test_questions = [
        "如何设置数字输出？",
        "moveL函数的参数说明",
        "如何获取TCP位置？"
    ]
    
    for q in test_questions:
        print(f"\n问题: {q}")
        print("回答:")
        print(rag_service.query(q))
        print("-" * 50)

