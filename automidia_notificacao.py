import json
import os
import sys
import logging
import csv
import cx_Oracle
import sqlite3
import time
import schedule
import requests
from threading import Thread
from typing import Dict
from datetime import datetime

def work_hour():
    agora = datetime.now()
    dia_semana = agora.weekday()  # 0 = segunda, 6 = domingo
    hora = agora.hour
    return 0 <= dia_semana <= 4 and 8 <= hora < 18

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('log.txt'),
        logging.StreamHandler(sys.stdout)
        
    ]
)
logger = logging.getLogger(__name__)

class DatabaseConnector:
    def __init__(self, config_file: str = 'db_config.json'): #Configurações inicias
        self.config_file = config_file
        self.connection = None
        self.cursor = None
        self.db_type = None
        self.config = self._load_config()

    def _load_config(self): #Função para validar o banco de dados do Automidia
        with open(self.config_file, 'r') as f: #Abrir o arquivo
            config = json.load(f) #Carregar o arquivo
            keys_login = ['db_type', 'user', 'password', 'host', 'port', 'service'] #Os valores de conexão do banco de dados
            try:
                for key in keys_login:
                    if key not in config:
                        raise KeyError(f"Chave {key} não encontrada")
                    self.db_type = config['db_type'].lower()
                    return config
            except FileNotFoundError: #Trativa de erro para arquivo não encontrado
                logger.error(f"Arquivo de configuração '{self.config_file}' não encontrado.")
                raise
            except json.JSONDecodeError: #Tratativa de erro para arquivo não decodificado
                logger.error(f"Erro ao decodificar o arquivo JSON '{self.config_file}'.")
                raise
            except KeyError as e: #Tratativa de erro quando as chaves estiverem incompletas
                logger.error(f"Configuração incompleta: {str(e)}")
                raise
    
    def connect(self): #Função para conectar no banco de dados do Automidia
        try:
            if self.db_type == 'oracle': #Iremos verificar as informações (O BANCO PRECISA SER ORACLE)
                dsn = cx_Oracle.makedsn(
                    self.config['host'],
                    self.config['port'],
                    service_name = self.config['service'] 
                )
                self.connection = cx_Oracle.connect(
                    user = self.config['user'],
                    password = self.config['password'],
                    dsn = dsn
                )
            else: #Tratativa de erros
                logger.error(f"Tipo de banco de dados não suportado: {self.db_type}")
                return False
            self.cursor = self.connection.cursor()
            logger.info(f"Conexão bem-sucedida com o banco de dados {self.db_type}")
            return True
        except Exception as e: #Tratativa de erros
            logger.error(f"Erro ao conectar ao banco de dados: {str(e)}")
            return False
    
    def generate_seguranca_acessos_report(self, output_file: str = None): #Função para executar a query
        if not self.connection or not self.cursor: #Caso a conexão não exista, ele parará
            logger.error("Conexão com o banco de dados não estabelecida.")
            return False

        #Query para conseguir os chamados pendentes
        query = """
        SELECT * FROM request r 
        WHERE ORIGGROUP = 'SEGURANCA ACESSOS'
        AND CATEGORY = 'Acessos'
        AND RSTATUS = 'Aguardando aprovacao'
        AND APROVCLITYPE in (2, 4)
        """

        try:
            self.cursor.execute(query) #Executa a query
            rows = self.cursor.fetchall()
            column_names = [desc[0] for desc in self.cursor.description]

            if not output_file:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output_file = f"relatorio_acessos_pendentes.csv"
            
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile, delimiter=';')
                writer.writerow(column_names) #Escreve o cabeçalho
                writer.writerows(rows) #Escreve os dados

            logger.info(f"Relatório gerado com sucesso: {output_file}")
            return True
        
        except Exception as e: #Tratativa de dados
            logger.error(f"Erro ao gerar relatório: {str(e)}")
            return False
        
    def close(self): #Fechar o banco de dados
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
        logger.info("Conexão com o banco de dados fechada.")

class ClientReportGenerator:
    def __init__(self, db_connector: DatabaseConnector):
        self.db = db_connector
        self._setup_scheduling()
        self.last_processed = {}


    def _process_first_contacts(self):
        """Processa os primeiros contatos (verificação rápida + SQLite)"""
        report_file = "relatorio_acessos_pendentes.csv"
        if not os.path.exists(report_file):
            logger.error(f"Arquivo de relatório não encontrado: {report_file}")
            return

        with open(report_file, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile, delimiter=';')
            for row in reader:
                request_id = row['REQUEST']
                if not self._request_already_processed(request_id):
                    self._get_client_info(row['CLIENT'], row)
                    self._register_processed_request(request_id)

    def _process_follow_ups(self):
        """Processa os follow-ups (processamento completo)"""
        report_file = "relatorio_acessos_pendentes.csv"
        if not os.path.exists(report_file):
            logger.error(f"Arquivo de relatório não encontrado: {report_file}")
            return

        with open(report_file, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile, delimiter=';')
            for row in reader:
                self._get_client_info(row['CLIENT'], row)

    def _request_already_processed(self, request_id: str) -> bool:
        """Verifica se o request já foi processado no SQLite"""
        try:
            with sqlite3.connect('banco.db') as conn:
                cursor = conn.cursor()
                cursor.execute("""
                CREATE TABLE IF NOT EXISTS processed_requests (
                    request_id TEXT PRIMARY KEY,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)
                cursor.execute("""
                SELECT 1 FROM processed_requests WHERE request_id = ?
                """, (request_id,))
                return cursor.fetchone() is not None
        except sqlite3.Error as e:
            logger.error(f"Erro ao verificar request no SQLite: {str(e)}")
            return False

    def _register_processed_request(self, request_id: str):
        """Registra um request como processado no SQLite"""
        try:
            with sqlite3.connect('banco.db') as conn:
                cursor = conn.cursor()
                cursor.execute("""
                INSERT OR IGNORE INTO processed_requests (request_id) VALUES (?)
                """, (request_id,))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Erro ao registrar request no SQLite: {str(e)}")


    def _get_client_info(self, client_code: str, request_data: Dict):
        """Versão completa para follow-up (sua função original)"""
        if not self.db.connection or not self.db.cursor:
            logger.error("Conexão com o banco de dados não estabelecida.")
            return

        try:
            # Query básica para pegar informações do cliente
            client_query = """
            SELECT c.CLIENT, c.FULLNAME, c.BOSS
            FROM client c 
            WHERE c.CLIENT = :client_code_param
            """
            
            self.db.cursor.execute(client_query, {"client_code_param": client_code})
            client_info = self.db.cursor.fetchone()

            if not client_info:
                logger.warning(f"Nenhum dado encontrado para o cliente: {client_code}")
                return
            
            column_names = [desc[0] for desc in self.db.cursor.description]
            client_dict = dict(zip(column_names, client_info))
            
            aprovclitype = request_data.get('APROVCLITYPE')
            clientaprov = request_data.get('CLIENTAPROV')
            
            # Determinar o código do aprovador
            approver_code = None
            if aprovclitype == '2':
                approver_code = client_dict.get('BOSS')
            elif aprovclitype == '4':
                approver_code = clientaprov
            
            # Buscar informações do aprovador
            approver_dict = {}
            if approver_code:
                approver_query = """
                SELECT CLIENT, FULLNAME, EMAILID
                FROM client
                WHERE CLIENT = :approver_code_param
                """
                self.db.cursor.execute(approver_query, {"approver_code_param": approver_code})
                approver_info = self.db.cursor.fetchone()
                if approver_info:
                    approver_columns = [desc[0] for desc in self.db.cursor.description]
                    approver_dict = dict(zip(approver_columns, approver_info))
            
            # Payload da requisição
            payload = {
                "tituloChamado": request_data.get('REQUEST', 'N/A'),
                "statusChamado": request_data.get('RSTATUS', 'N/A'),
                "descricaoChamado": request_data.get('DESCRIPT', 'N/A'),
                "emailAprovador": approver_dict.get('EMAILID', 'N/A'),
                "clienteNome": client_dict.get('FULLNAME', 'N/A')
            }

            self._send_payload(payload)

        except cx_Oracle.DatabaseError as e:
            error, = e.args
            logger.error(f"Erro Oracle {error.code}: {error.message}")
        except Exception as e:
            logger.error(f"Erro no processamento: {str(e)}")

    def _send_payload(self, payload: Dict):
        """Envia o payload para a API"""
        url = f"https://prod-00.brazilsouth.logic.azure.com:443/workflows/4546cd4eebdf43ca882aa13cf6287a45/triggers/When_a_HTTP_request_is_received/paths/invoke?api-version=2016-10-01&sp=%2Ftriggers%2FWhen_a_HTTP_request_is_received%2Frun&sv=1.0&sig=x3yXIT9oV_pXmOa5C3sD--JcpNuLno9pguY3gLxnjmM"  
        headers = {"Content-Type": "application/json"}
        
        try:
            response = requests.post(url, json=payload, headers=headers)
            if response.status_code in (200, 202):
                logger.info(f"Payload enviado com sucesso. Status: {response.status_code}")
            else:
                logger.error(f"Erro ao enviar payload: {response.status_code} - {response.text}")
        except requests.RequestException as e:
            logger.error(f"Erro na requisição HTTP: {str(e)}")

def work_hour():
    agora = datetime.now()
    dia_semana = agora.weekday()  # 0 = segunda, 6 = domingo
    hora = agora.hour
    return 0 <= dia_semana <= 4 and 8 <= hora < 18


if __name__ == "__main__":
    db = DatabaseConnector('connection.json')
    if db.connect():
        try:
            report_generator = None  # Inicializa como None

            while True:
                if work_hour():
                        db.generate_seguranca_acessos_report()
                else:
                    if report_generator is not None:
                        logger.info("Fora do horário comercial. Parando processador.")
                        report_generator = None  # Libera o objeto para recriação depois
                time.sleep(180)
        except KeyboardInterrupt:
            logger.info("Encerrando o serviço...")
        finally:
            db.close()
