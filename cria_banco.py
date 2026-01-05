import sqlite3
from datetime import datetime

# Caminho do banco de dados
db_path = 'banco.db'

def criar_banco_de_dados():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Criar a tabela de log
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS Chamados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request TEXT NOT NULL,
            client TEXT NOT NULL,
            aprovador TEXT NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()


if __name__ == "__main__":
    criar_banco_de_dados()
    print("Banco de dados e tabela de log criados com sucesso!")