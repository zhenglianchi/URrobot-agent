
from abc import ABC, abstractmethod
from langchain_core.embeddings import Embeddings
from langchain_community.chat_models.tongyi import BaseChatModel
from langchain_community.embeddings import DashScopeEmbeddings
from langchain_community.chat_models.tongyi import ChatTongyi


class BaseModelFactory(ABC):
    @abstractmethod
    def generator(self):
        pass


class ChatModelFactory(BaseModelFactory):
    def __init__(self, api_key="sk-43e0b9c055a243a7ad60273715ba25c0", model_name="qwen3.5-plus"):
        self.api_key = api_key
        self.model_name = model_name
    
    def generator(self):
        return ChatTongyi(model=self.model_name, dashscope_api_key=self.api_key)


class EmbeddingsFactory(BaseModelFactory):
    def __init__(self, api_key="sk-43e0b9c055a243a7ad60273715ba25c0", model_name="text-embedding-v4"):
        self.api_key = api_key
        self.model_name = model_name
    
    def generator(self):
        return DashScopeEmbeddings(model=self.model_name, dashscope_api_key=self.api_key)


chat_model = ChatModelFactory().generator()
embed_model = EmbeddingsFactory().generator()

