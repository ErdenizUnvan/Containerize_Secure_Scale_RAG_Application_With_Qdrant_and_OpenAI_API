from flask import Flask, request, jsonify
from flask_restx import Api, Resource, reqparse
from flask_jwt_extended import JWTManager, create_access_token, jwt_required, get_jwt_identity, get_jwt
from datetime import timedelta
import os
from ldap3 import Server, Connection, ALL
import time
import logging
from llama_index.core.indices.composability import ComposableGraph
from llama_index.core.indices.base import BaseIndex
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

class Category(str, Enum):
    related_to_ccnp_sp = 'related_to_ccnp_sp'
    related_to_ccnp_devnet = 'related_to_ccnp_devnet'
    not_related = 'not_related'

class ResultModel(BaseModel):
    result: Category

apikey=''

intent_model = ChatOpenAI(model="gpt-3.5-turbo", temperature=0, api_key=apikey)

parser = PydanticOutputParser(pydantic_object=ResultModel)

Settings.llm = LlamaOpenAI(
    model="gpt-3.5-turbo",
    api_key=apikey,
    temperature=1.0,
    max_tokens=512
)

# === Ayarlar ===
Settings.embed_model = LangchainEmbedding(
    OpenAIEmbeddings(model="text-embedding-3-small",
    api_key=apikey)  # veya text-embedding-ada-002
)

client = QdrantClient(host="172.20.0.201", port=6333)


app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = 'super-secret'
jwt = JWTManager(app)
api = Api(app)


@api.route('/login')
class Login(Resource):
    def post(self):
        """Login to get JWT token with optional expiration time"""
        data = request.get_json()
        if not data or not data.get('username') or not data.get('password'):
            return {'message': 'Credentials required'}, 401
        username = data.get('username')
        password = data.get('password')


        try:
            server = Server('ldap://10.1.100.133', get_info=ALL)
            user_dn = f'{username}@test.com'
            conn = Connection(server, user=user_dn,
                              password=password,
                              authentication='SIMPLE',
                              auto_bind=True)
            if not conn:
                raise ValueError()

            conn.search('dc=test,dc=com',
                f'(sAMAccountName={username})',
                attributes=['memberOf'])
            if conn.entries:
                groups = conn.entries[0]['memberOf']
                group_name = None
                for g in groups:
                    g_str = str(g)
                    if g_str == 'CN=kcusers,DC=test,DC=com':
                        group_name = 'kcusers'

                if not group_name:
                    logger.error(f"username:{username}, Unauthorized group")
                    return {'message': 'Unauthorized group'}, 403

                #print(f"Grup: {group_name}")

                expires_in = data.get('expires_in', 15)
                expiration_delta = timedelta(minutes=int(expires_in))

                # identity içerisine kullanıcı adı ve grubu koy
                access_token = create_access_token(identity=username,
                                   expires_delta=expiration_delta,
                                   additional_claims={'group': group_name})

                logger.info(f"Giriş başarılı: {username}, Grup: {group_name}")
                return {'access_token': access_token, 'expires_in': f'{expires_in} minutes'}, 200
            else:
                logger.error(f"username:{username} login olma hatasi: {str(e)}")
                raise ValueError()

        except Exception as e:
            #print("Şifre yanlış veya kullanıcı bulunamadı.")
            logger.error(f"username:{username} login olma hatasi: {str(e)}")
            return {'message': 'Invalid credentials'}, 401

query_parser=reqparse.RequestParser()

query_parser.add_argument('query',
                       type=str,
                       required=True,
                        help='soru yaz')

@api.route('/chat')
class Register(Resource):
    @jwt_required()  # JWT doğrulama
    @api.expect(query_parser)
    def post(self):
        """Add a new device (Root only with JWT authentication)"""
        username = get_jwt_identity()
        claims = get_jwt()
        group = claims.get('group')

        apikey='sk-proj-L2MgIQhNcmER3yEpR8u0T3BlbkFJyBQOcjdM8CowLGe3d8U1'
        args=query_parser.parse_args()
        query=args.query

        if not query or query.isspace():
            return "Lütfen bir soru yazın."
        prompt = (
            "You are an AI assistant that classifies the user's question into one of the following categories:\n"
            "- related_to_ccnp_sp → If the question is about CCNP **Service Provider** topics (like IS-IS, MPLS, Segment Routing, etc).\n"
            "- related_to_ccnp_devnet → If the question is about CCNP **DevNet** topics (like network automation, Python, APIs, Netconf, RESTCONF, YANG).\n"
            "- not_related → If the question is not related to any CCNP topic.\n\n"
            f"User question: \"{query}\"\n\n"
            "Respond **only** in this exact JSON format:\n"
            '{\n'
            '  "result": "<related_to_ccnp_sp or related_to_ccnp_devnet or not_related>"\n'
            '}'
        )

        try:
            response = intent_model.invoke(prompt)
            parsed = parser.parse(response.content)

            print(f"\nSınıf: {parsed.result}")

        except Exception as e:
            return f"Agent error: {e}"

        if str(parsed.result)=='Category.not_related':
            logger.error(f"username:{username}, Grup:{group}, alakasiz soru:{query}")
            return 'out of scope'

        #if group in ['kcusers']:
        if str(parsed.result)=='Category.related_to_ccnp_devnet':
            logger.info(f"username:{username}, Grup:{group} ile giris: /chat: CCNP Devnet, query:{query}")
            #return 'out of scope'
            collections = ["DEVASC", "NPDESI"]
            indexes = []
            summaries = []
            flag=False



            for col in collections:
                if not client.collection_exists(col):
                    print(f"Koleksiyon bulunamadı: {col}")
                    flag=True
                else:
                    print(f"Koleksiyon bulundu: {col}")
                    vstore = QdrantVectorStore(client=client, collection_name=col)
                    storage = StorageContext.from_defaults(vector_store=vstore)
                    index = VectorStoreIndex.from_vector_store(vstore, storage_context=storage)
                    indexes.append(index)
                    summaries.append(f"This index contains content from {col} of the CCNP Service Provider book.")  # Summary şart!
            if flag:
                logger.error(f"username:{username}, Grup:{group}, query:{query}, Geçerli koleksiyon bulunamadi")
                return "Geçerli koleksiyon bulunamadı, çıkılıyor."
            if not indexes:
                logger.error(f"username:{username}, Grup:{group}, query:{query}, İlgili bölüm bulanamadı")
                return "İlgili bölüm bulanamadı ."
            else:

                # === ComposableGraph ile birleştir ===
                graph = ComposableGraph.from_indices(root_index=indexes[0],
                        children_indices=indexes[1:],
                        index_summaries=summaries[1:],   #Zorunlu: SPROUTE2, SPCORE1, SPCORE2 açıklamaları
                        root_index_cls=VectorStoreIndex,
                        include_text=True,)
                query_engine = graph.as_query_engine()

                try:
                    response = query_engine.query(query)
                    logger.info(f"username:{username}, Grup:{group} ile giris: /chat: CCNP Devnet, reply:{response.response}")
                    return response.response

                except Exception as e:
                    return f"Hata:{str(e)}"


        #if group in ['kcroot']:
        if str(parsed.result)=='Category.related_to_ccnp_sp':
            #return 'out of scope'
            logger.info(f"username:{username}, Grup:{group} ile giris: /chat: CCNP Service Provider, query:{query}")
            collections = ["SPROUTE1", "SPROUTE2", "SPCORE1", "SPCORE2"]
            indexes = []
            summaries = []
            flag=False

            for col in collections:
                if not client.collection_exists(col):
                    flag=True
                else:
                    print(f"Koleksiyon bulundu: {col}")
                    vstore = QdrantVectorStore(client=client, collection_name=col)
                    storage = StorageContext.from_defaults(vector_store=vstore)
                    index = VectorStoreIndex.from_vector_store(vstore, storage_context=storage)
                    indexes.append(index)
                    summaries.append(f"This index contains content from {col} of the CCNP Service Provider book.")  # Summary şart!
            if flag:
                logger.error(f"username:{username}, Grup:{group}, query:{query}, Geçerli koleksiyon bulunamadi")
                return "Geçerli koleksiyonlar bulunamadı"
            if not indexes:
                logger.error(f"username:{username}, Grup:{group}, query:{query}, İlgili bölüm bulanamadı")
                return "İlgili bölüm bulanamadı ."
            else:

                # === ComposableGraph ile birleştir ===
                graph = ComposableGraph.from_indices(root_index=indexes[0],
                        children_indices=indexes[1:],
                        index_summaries=summaries[1:],   #Zorunlu: SPROUTE2, SPCORE1, SPCORE2 açıklamaları
                        root_index_cls=VectorStoreIndex,
                        include_text=True,)
                query_engine = graph.as_query_engine()

                try:
                    response = query_engine.query(query)
                    logger.info(f"username:{username}, Grup:{group} ile giris: /chat: CCNP Service Provider, reply:{response.response}")
                    return response.response

                except Exception as e:
                    return f"Hata:{str(e)}"

if __name__ =='__main__':
    app.run(debug=True,
    host='0.0.0.0',
    port=8443,
    ssl_context=('certificate.pem', 'privatekey.pem'))

