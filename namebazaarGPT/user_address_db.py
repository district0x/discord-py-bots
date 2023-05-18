import sqlite3

class UserAddressDB:
    def __init__(self, db_file):
        self.db_file = db_file
        self._create_tables()

    def _create_tables(self):
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS user_address (
                    user TEXT,
                    address TEXT,
                    tx_key TEXT,
                    signature TEXT,
                    updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (user, address)
                )
            ''')
            conn.commit()

    def add_user_address(self, user, address, tx_key, signature):
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT OR REPLACE INTO user_address (user, address, tx_key, signature)
                VALUES (?, ?, ?, ?)
            ''', (user, address, tx_key, signature))
            conn.commit()

    def get_user(self, address):
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user FROM user_address
                WHERE address = ?
            ''', (address,))
            result = cursor.fetchone()
            if result:
                return result[0]
            else:
                return None

    def get_address(self, user):
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT address FROM user_address
                WHERE user = ?
            ''', (user,))
            result = cursor.fetchone()
            if result:
                return result[0]
            else:
                return None
