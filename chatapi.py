from flask import Flask, request, jsonify
from flask_restx import Api, Resource, reqparse
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, get_jwt
from datetime import timedelta
from ldap3 import Server, Connection, ALL
import time
import logging
from qdrant_client import QdrantClient
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.core import Settings, VectorStoreIndex, StorageContext
from llama_index.embeddings.langchain import LangchainEmbedding
from langchain_openai import OpenAIEmbeddings
from llama_index.llms.openai import OpenAI as LlamaOpenAI
import warnings
warnings.filterwarnings('ignore')
from langchain_openai import ChatOpenAI
from enum import Enum
from pydantic import BaseModel
from langchain_core.output_parsers import PydanticOutputParser
from qdrant_client.models import VectorParams
from llama_index.readers.file import PDFReader
from llama_index.core.node_parser import SimpleNodeParser
import os
from dotenv import load_dotenv
load_dotenv()
# === Logging yapılandırması ===


log_dir = "/logs"
os.makedirs(log_dir, exist_ok=True)
log_path = os.path.join(log_dir, "app.log")

# Handler'ları ayrı tanımla
file_handler = logging.FileHandler(log_path)
stream_handler = logging.StreamHandler()

# Formatter oluştur
formatter = logging.Formatter(
    fmt='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
file_handler.setFormatter(formatter)
stream_handler.setFormatter(formatter)

# Logger ayarları
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(file_handler)
logger.addHandler(stream_handler)


OPENAI_LLM_MODEL=os.getenv('OPENAI_LLM_MODEL')
OPENAI_TOKEN=os.getenv('OPENAI_TOKEN')
OPENAI_TEXT_EMBED_MODEL=os.getenv('OPENAI_TEXT_EMBED_MODEL')
LDAP_URI=os.getenv('LDAP_URI')
LDAP_UPN_SUFFIX=os.getenv('LDAP_UPN_SUFFIX')
LDAP_BASE_DN=os.getenv('LDAP_BASE_DN')
LDAP_ALLOWED_GROUP_name1=os.getenv('LDAP_ALLOWED_GROUP_name1')
LDAP_ALLOWED_GROUP_name2=os.getenv('LDAP_ALLOWED_GROUP_name2')
CERT_PATH=os.getenv('CERT_PATH')
KEY_PATH=os.getenv('KEY_PATH')
APP_PORT=os.getenv('APP_PORT')
JWT_SECRET_KEY=os.getenv('JWT_SECRET_KEY')
QdrantClienthost=os.getenv('QdrantClienthost')

def ldap_login(username, password):
    conn = None

    try:
        server = Server(LDAP_URI, get_info=ALL)

        conn = Connection(
            server,
            user=f"{username}@{LDAP_UPN_SUFFIX}",
            password=password,
            auto_bind=True
        )

        conn.search(
            LDAP_BASE_DN,
            f"(sAMAccountName={username})",
            attributes=["memberOf"]
        )

        groups = str(conn.entries)

        if LDAP_ALLOWED_GROUP_name2 in groups:
            return True, LDAP_ALLOWED_GROUP_name2

        elif LDAP_ALLOWED_GROUP_name1 in groups:
            return True, LDAP_ALLOWED_GROUP_name1

        return False, "unauthorized group"

    except Exception as e:
        logger.error(
            f"username:{username} login olma hatasi: {str(e)}"
        )
        return False, str(e)

    finally:
        if conn is not None:
            conn.unbind()


class Category(str, Enum):
    related_to_ccnp_sp = 'related_to_ccnp_sp'
    related_to_ccnp_devnet = 'related_to_ccnp_devnet'
    not_related = 'not_related'

class ResultModel(BaseModel):
    result: Category

os.environ['OPENAI_API_KEY'] = OPENAI_TOKEN

intent_model = ChatOpenAI(model=OPENAI_LLM_MODEL, temperature=0)

parser = PydanticOutputParser(pydantic_object=ResultModel)

Settings.llm = LlamaOpenAI(
    model=OPENAI_LLM_MODEL,
    api_key=OPENAI_TOKEN,
    temperature=1.0,
    max_tokens=512
)

# === Ayarlar ===
Settings.embed_model = LangchainEmbedding(
    OpenAIEmbeddings(model=OPENAI_TEXT_EMBED_MODEL,
    api_key=OPENAI_TOKEN)  # veya text-embedding-ada-002
)

client = QdrantClient(host=QdrantClienthost, port=6333)


app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = JWT_SECRET_KEY
jwt = JWTManager(app)
api = Api(app)


@api.route("/login")
class Login(Resource):
    def post(self):
        data = request.get_json() or {}
        username = data.get("username")
        password = data.get("password")
        if not username or not password:
            return {
                "message": "Username and password required"
            }, 400


        status,output=ldap_login(username, password)
        if not status:
            return {
                "message": output
            }, 401

        else:
            group_name=output
            expires_in = int(data.get("expires_in", 15))

            access_token = create_access_token(
                identity=username,
                expires_delta=timedelta(minutes=expires_in),
                additional_claims={"group": group_name})
            logger.info(f"Giriş başarılı: {username}, Grup: {group_name}")
            return {
                "access_token": access_token,
                "expires_in": f"{expires_in} minutes",
                "group": group_name
            }, 200


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


pdf_parser=reqparse.RequestParser()

pdf_parser.add_argument('pdf',
                       type=str,
                       required=True,
                        help='upload edilecek pdf dosyasinin ismini yaz')

@api.route('/add_pdf')
class add_pdf(Resource):
    @jwt_required()  # JWT doğrulama
    @api.expect(pdf_parser)
    def post(self):
        username = get_jwt_identity()
        claims = get_jwt()
        group = claims.get('group')

        if group != LDAP_ALLOWED_GROUP_name2:
            return {
                "message": f"unauthorized group:{group}"
            }, 403
        args=pdf_parser.parse_args()
        pdf_file=args.pdf
        collection = pdf_file[:-4]
        out = upload_pdf_to_qdrant(pdf_file,collection)
        return out

@api.route('/get_pdf')
class get_pdf(Resource):
    @jwt_required()  # JWT doğrulama
    def get(self):
        username = get_jwt_identity()
        claims = get_jwt()
        group = claims.get('group')

        if group != LDAP_ALLOWED_GROUP_name2:
            return {
                "message": f"unauthorized group:{group}"
            }, 403

        db = client.get_collections()

        if len(db.collections) == 0:
            return "collection yok zaten"
        else:
            dosyalar = []

            for col in db.collections:
                dosyalar.append(col.name)

            return dosyalar

@api.route('/delete_pdf')
class delete_pdf(Resource):
    @jwt_required()  # JWT doğrulama
    @api.expect(pdf_parser)
    def delete(self):
        username = get_jwt_identity()
        claims = get_jwt()
        group = claims.get('group')

        if group != LDAP_ALLOWED_GROUP_name2:
            return {
                "message": f"unauthorized group:{group}"
            }, 403
        args=pdf_parser.parse_args()
        pdf_file=args.pdf
        collection = pdf_file[:-4]
        if client.collection_exists(collection):
            client.delete_collection(collection_name=collection)
            return f"'{collection}' koleksiyonu silindi."
        else:
            return f"'{collection}' koleksiyonu zaten yok."

query_parser = reqparse.RequestParser()

query_parser.add_argument('query',
    type=str,
    required=True,
    help='soru yaz')

@api.route('/chat')
class Register(Resource):

    @jwt_required()
    @api.expect(query_parser)
    def post(self):

        username = get_jwt_identity()

        claims = get_jwt()
        group = claims.get('group')

        args = query_parser.parse_args()
        query = args.query

        if not query or query.isspace():
            return "Lütfen bir soru yazın."

        # =========================================================
        # INTENT CLASSIFICATION
        # =========================================================

        prompt = (
            "You are an AI assistant that classifies the user's question "
            "into one of the following categories:\n"

            "- related_to_ccnp_sp → If the question is about CCNP "
            "Service Provider topics "
            "(like IS-IS, MPLS, Segment Routing, BGP, etc).\n"

            "- related_to_ccnp_devnet → If the question is about CCNP "
            "DevNet topics "
            "(like network automation, Python, APIs, NETCONF, "
            "RESTCONF, YANG).\n"

            "- not_related → If the question is not related to "
            "any CCNP topic.\n\n"

            f'User question: "{query}"\n\n'

            "Respond only in this exact JSON format:\n"

            '{\n'
            '  "result": '
            '"<related_to_ccnp_sp or related_to_ccnp_devnet or not_related>"\n'
            '}'
        )

        try:
            response = intent_model.invoke(prompt)
            parsed = parser.parse(response.content)
            print(f"\nSınıf: {parsed.result}")
        except Exception as e:
            logger.error(
                f"username:{username}, "
                f"Grup:{group}, "
                f"Intent Classification Agent error:{e}"
            )
            return f"Agent error: {e}"
        # =========================================================
        # COLLECTION SEÇİMİ
        # =========================================================
        if parsed.result == Category.not_related:
            logger.error(
                f"username:{username}, "
                f"Grup:{group}, "
                f"alakasiz soru:{query}"
            )
            return "out of scope"
        elif parsed.result == Category.related_to_ccnp_devnet:
            logger.info(
                f"username:{username}, "
                f"Grup:{group} ile giris: "
                f"/chat: CCNP Devnet, "
                f"query:{query}"
            )
            collections = [
                "DEVASC",
                "NPDESI"
            ]
        elif parsed.result == Category.related_to_ccnp_sp:
            logger.info(
                f"username:{username}, "
                f"Grup:{group} ile giris: "
                f"/chat: CCNP Service Provider, "
                f"query:{query}"
            )
            collections = [
                "SPROUTE1",
                "SPROUTE2",
                "SPCORE1",
                "SPCORE2"
            ]
        else:
            return "Kategori belirlenemedi."

        # =========================================================
        # TÜM İLGİLİ COLLECTION'LARDAN RETRIEVAL
        # =========================================================
        retrieved_contexts = []
        for col in collections:
            if not client.collection_exists(col):
                print(f"Koleksiyon bulunamadı: {col}")
                continue
            print(f"Koleksiyon bulundu: {col}")
            try:
                # Qdrant Vector Store
                vstore = QdrantVectorStore(
                    client=client,
                    collection_name=col
                )
                # Existing Qdrant collection üzerinden index oluştur
                index = VectorStoreIndex.from_vector_store(vstore)
                # Her collection'dan en iyi 3 chunk
                retriever = index.as_retriever(similarity_top_k=3)
                nodes = retriever.retrieve(query)
                print(f"{col} -> {len(nodes)} sonuç")
                # Debug çıktısı
                for node in nodes:
                    print(
                        f"[{col}] "
                        f"score={node.score} | "
                        f"{node.text[:200]}")
                    retrieved_contexts.append(
                        f"\n"
                        f"SOURCE COLLECTION: {col}\n"
                        f"SIMILARITY SCORE: {node.score}\n"
                        f"{node.text}")
            except Exception as e:
                logger.error(
                    f"username:{username}, "
                    f"collection:{col}, "
                    f"retrieval error:{str(e)}")
                print(f"{col} retrieval hatası: {e}")
        # =========================================================
        # CONTEXT KONTROLÜ
        # =========================================================
        if not retrieved_contexts:
            logger.error(
                f"username:{username}, "
                f"Grup:{group}, "
                f"query:{query}, "
                f"retrieval sonucu bulunamadı")
            return ("Bu konu ile ilgili Qdrant üzerinde bilgi bulunamadı.")
        # Bütün collection sonuçlarını tek context haline getir
        context = "\n\n".join(retrieved_contexts)
        # =========================================================
        # FINAL RAG PROMPT
        # =========================================================
        final_prompt = f"""
You are a CCNP technical assistant.

Your task is to answer the user's question using ONLY
the provided CCNP course context retrieved from Qdrant.

RULES:

1. Use only information contained in the provided context.

2. If relevant information exists in multiple collections,
combine the information into one clear technical answer.

3. Do not invent information that is not present in the context.

4. Do not say that information is unavailable if relevant
information exists anywhere in the provided context.

5. Prefer the most relevant retrieved passages when
constructing the answer.

6. Give a clear and technically accurate CCNP-level explanation.

USER QUESTION:

{query}


CCNP COURSE CONTEXT:

{context}
"""
        # =========================================================
        # LLM RESPONSE
        # =========================================================
        try:
            response = Settings.llm.complete(final_prompt)
            answer = response.text
            logger.info(
                f"username:{username}, "
                f"Grup:{group}, "
                f"query:{query}, "
                f"reply:{answer}")
            return answer
        except Exception as e:
            logger.error(
                f"username:{username}, "
                f"Grup:{group}, "
                f"query:{query}, "
                f"LLM error:{str(e)}")
            return f"Hata:{str(e)}"

if __name__ =='__main__':
    app.run(debug=True,
    host='0.0.0.0',
    port=8443,
    ssl_context=(CERT_PATH, KEY_PATH))
