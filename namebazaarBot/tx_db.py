import sqlite3


class TxDB:
    def __init__(self, db_file):
        self.db_file = db_file
        self._create_tables()

    def _create_tables(self):
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS tx (
                    tx_key TEXT,
                    tx_result TEXT,
                    user TEXT,
                    action TEXT,
                    channel TEXT,
                    next_action_data TEXT,
                    created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (tx_key)
                )
            ''')
            conn.execute('''CREATE INDEX IF NOT EXISTS idx_user ON tx (user)''')
            conn.execute('''CREATE INDEX IF NOT EXISTS idx_action ON tx (action)''')
            cursor.execute('''CREATE INDEX IF NOT EXISTS idx_created ON tx (created)''')
            conn.commit()

    def add_tx(self, tx):
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO tx (tx_key, user, action, channel, next_action_data)
                VALUES (?, ?, ?, ?, ?)
            ''', (tx['tx_key'], tx['user'], tx['action'], tx['channel'], tx['next_action_data']))
            conn.commit()

    def _dict_factory(self, cursor, row):
        return dict(zip([col[0] for col in cursor.description], row))

    def get_tx(self, tx_key):
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = self._dict_factory
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM tx WHERE tx_key = ?
            ''', (tx_key,))
            return cursor.fetchone()

    def get_txs_by_user_action(self, user, action):
        with sqlite3.connect(self.db_file) as conn:
            conn.row_factory = self._dict_factory
            cursor = conn.cursor()
            cursor.execute('''
                SELECT * FROM tx WHERE user = ? AND action = ?
            ''', (user, action))
            return cursor.fetchall()

    def update_tx_result(self, tx_key, tx_result):
        print()
        with sqlite3.connect(self.db_file) as conn:
            print(f"Running SQL: UPDATE tx SET tx_result = ? WHERE tx_key = ? AND tx_result IS NULL")
            print(f"WITH:  tx_key={tx_key}, tx_result={tx_result}")
            cursor = conn.cursor()
            cursor.execute('''
                UPDATE tx SET tx_result = ? WHERE tx_key = ? AND tx_result IS NULL
            ''', (tx_result, tx_key))
            conn.commit()
            if cursor.rowcount == 0:
                raise ValueError(
                    f"Failed to update tx_result for tx_key={tx_key}. tx_result may not be empty or tx_key may not exist.")

    def tx_key_exists(self, tx_key):
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT EXISTS(SELECT 1 FROM tx WHERE tx_key = ? LIMIT 1)
            ''', (tx_key,))
            return bool(cursor.fetchone()[0])

    def tx_result_exists(self, tx_key):
        with sqlite3.connect(self.db_file) as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT EXISTS(SELECT 1 FROM tx WHERE tx_key = ? AND tx_result IS NOT NULL LIMIT 1)
            ''', (tx_key,))
            return bool(cursor.fetchone()[0])
