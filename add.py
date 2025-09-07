from qdrant_client import QdrantClient
from qdrant_client.http.models import VectorParams
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.core import StorageContext, VectorStoreIndex, Settings
from llama_index.readers.file.docs.base import PDFReader
from llama_index.core.node_parser import SimpleNodeParser
from llama_index.embeddings.langchain import LangchainEmbedding
from langchain_openai import OpenAIEmbeddings  # ← OpenAI için bu
import os

# === OpenAI API anahtarını ortamdan çek (veya direkt yazabilirsin) ===
apikey=''
os.environ["OPENAI_API_KEY"] = apikey  # Buraya kendi anahtarını koy

# === Embed modeli OpenAI üzerinden ===
Settings.embed_model = LangchainEmbedding(
    OpenAIEmbeddings(model="text-embedding-3-small")  # veya text-embedding-ada-002
)
print('embed_model ok')

# === Qdrant bağlantısı ===
client = QdrantClient(host="172.20.0.201", port=6333)

def ensure_collection(client, collection_name):
    if client.collection_exists(collection_name):
        print('Koleksiyon zaten var')
        return False, f"Koleksiyon zaten var: {collection_name}"
    else:
        print('Koleksiyon yok')
        client.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=1536, distance="Cosine")  # text-embedding-3-small için
        )
        print('Koleksiyon uretildi')
        return True, f"Yeni koleksiyon oluşturuldu: {collection_name}"

def upload_pdf_to_qdrant(file, collection_name):
    try:
        check_status,check_explanation=ensure_collection(client,collection_name)
        if not check_status:
            return check_explanation
        else:
            print('PDF dosyası bulundu linux path icinde')
            # PDF yükle ve parçalara böl
            documents = PDFReader().load_data(file)
            print('documents ok')
            for doc in documents:
                doc.metadata = {"source": collection_name}
            node_parser = SimpleNodeParser(chunk_size=512, chunk_overlap=50)
            print('parser ok')

            # Qdrant vector store ayarla
            vector_store = QdrantVectorStore(client=client, collection_name=collection_name)
            print('vector_store ok')
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            print('storage_context ok')

            # Dökümanları Qdrant’a yükle
            VectorStoreIndex.from_documents(
                documents,
                storage_context=storage_context,
                node_parser=node_parser,
                show_progress=True
            )
            print('VectorStoreIndex ok')

            return f"'{file}' dosyası '{collection_name}' koleksiyonuna yüklendi."

    except Exception as e:
        return f"Hata: {e}"

# === Komut satırından dosya al
file = input('file: ').strip()
if file not in os.listdir(os.getcwd()) or not file.endswith('.pdf'):
    print('PDF dosyası gerekli.')
else:
    collection = file[:-4]
    output = upload_pdf_to_qdrant(file, collection)
    print(output)
