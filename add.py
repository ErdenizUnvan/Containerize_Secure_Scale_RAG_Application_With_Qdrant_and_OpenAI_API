from qdrant_client import QdrantClient
from qdrant_client.http.models import VectorParams
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.core import StorageContext, VectorStoreIndex, Settings
from llama_index.readers.file.docs.base import PDFReader
from llama_index.core.node_parser import SimpleNodeParser
from llama_index.embeddings.langchain import LangchainEmbedding
from langchain_openai import OpenAIEmbeddings

import os
from dotenv import load_dotenv

load_dotenv()

openai_apikey = os.getenv("OPENAI_API_KEY")
os.environ["OPENAI_API_KEY"] = openai_apikey


# ==================================================
# OpenAI Embedding
# ==================================================

Settings.embed_model = LangchainEmbedding(
    OpenAIEmbeddings(
        model="text-embedding-3-small"
    )
)

print("embed_model ok")


# ==================================================
# Qdrant
# ==================================================

client = QdrantClient(
    host="192.168.56.112",
    port=6333,
    timeout=60
)


def ensure_collection(client, collection_name):

    if client.collection_exists(collection_name):

        return False, f"Koleksiyon zaten var: {collection_name}"

    else:

        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(
                size=1536,
                distance="Cosine"
            )
        )

        return True, f"Yeni koleksiyon oluşturuldu: {collection_name}"


# ==================================================
# PDF yükleme
# ==================================================

def upload_pdf_to_qdrant(file: str, collection_name: str):

    try:

        if (
            file not in os.listdir(os.getcwd())
            or not os.path.isfile(file)
            or not file.endswith(".pdf")
        ):
            return "PDF dosyası gerekli."


        created, msg = ensure_collection(
            client,
            collection_name
        )

        if created is False:
            raise ValueError(msg)


        # 1) PDF oku

        documents = PDFReader().load_data(file)

        print("documents ok")


        # 2) Chunk

        node_parser = SimpleNodeParser(
            chunk_size=512,
            chunk_overlap=50
        )

        print("parser ok")


        # 3) Qdrant Vector Store

        vector_store = QdrantVectorStore(
            client=client,
            collection_name=collection_name
        )

        storage_context = StorageContext.from_defaults(
            vector_store=vector_store
        )

        print("vector_store & storage_context ok")


        # 4) Embedding + Qdrant

        VectorStoreIndex.from_documents(
            documents,
            storage_context=storage_context,
            node_parser=node_parser,
            show_progress=True
        )

        print("VectorStoreIndex ok")


        return (
            f"'{file}' dosyası "
            f"'{collection_name}' koleksiyonuna yüklendi."
        )


    except Exception as e:

        return f"Hata: {e}"


# ==================================================
# CLI
# ==================================================

if __name__ == "__main__":
    file = input("file: ").strip()
    collection = file[:-4]
    out = upload_pdf_to_qdrant(file,collection)
    print(out)
