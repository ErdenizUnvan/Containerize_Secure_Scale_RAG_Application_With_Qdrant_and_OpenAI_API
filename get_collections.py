#pip install qdrant_client
from qdrant_client import QdrantClient

# Qdrant'a bağlan
client = QdrantClient(
    host="192.168.56.112",
    port=6333,
    timeout=60
)
# Koleksiyonların listesini al
collections = client.get_collections()
if len(collections.collections)==0:
    print('collection yok zaten')
else:
    for col in collections.collections:
        print(f"{col.name}")
